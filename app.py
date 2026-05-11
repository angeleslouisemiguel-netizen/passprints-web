"""
PassPrint DTF CRM — Flask + Gmail OAuth
Features:
• Gmail OAuth2 login — session persists across refreshes
• Admin panel — owner can whitelist users and grant admin rights
• Google Sheets sync — customers auto-loaded from your DTF spreadsheet
• All original CRM features intact (orders, customers, quotes, receipts)
"""

import os, json, functools, secrets, urllib.parse
import requests as http_requests
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, abort)
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dtf-crm-super-secret-2026-change-me")

# ── Google OAuth config ───────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID",     "824885091219-tkbocj406dtdktudmrldiq71ba60kj78.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "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")
REDIRECT_URI         = os.environ.get("REDIRECT_URI",         "https://passprint-dtf.onrender.com/auth/callback")

# ── Google Sheet config ───────────────────────────────────────
# Your DTF customers spreadsheet (sheet tab gid=496204286)
# Make sure it is shared: File → Share → Anyone with the link → Viewer
SHEET_ID  = os.environ.get("SHEET_ID",  "1WC8nUW7_07dPmPetNCtHzeAXkkulDPzw")
SHEET_GID = os.environ.get("SHEET_GID", "496204286")

# ── Owner / whitelist config ──────────────────────────────────
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")
USERS_FILE  = os.path.join(os.path.dirname(__file__), "users.json")


def load_users():
    if not os.path.exists(USERS_FILE):
        data = {}
        if OWNER_EMAIL:
            data[OWNER_EMAIL] = {"email": OWNER_EMAIL, "name": "Owner", "admin": True, "allowed": True}
        _save_users(data)
        return data
    try:
        with open(USERS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def save_users(data):
    _save_users(data)

def get_user(email):
    return load_users().get(email)

def is_allowed(email):
    if OWNER_EMAIL and email == OWNER_EMAIL:
        return True
    u = get_user(email)
    return u is not None and u.get("allowed", False)

def is_admin(email):
    if OWNER_EMAIL and email == OWNER_EMAIL:
        return True
    u = get_user(email)
    return u is not None and u.get("admin", False)


# ── Auth decorators ───────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper

def access_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = session.get("user")
        if not user:
            return redirect(url_for("login_page"))
        if not is_allowed(user["email"]):
            return render_template("pending.html", user=user)
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = session.get("user")
        if not user or not is_admin(user["email"]):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ── OAuth flow ────────────────────────────────────────────────
GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES    = "openid email profile"

def build_auth_url(state):
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         GOOGLE_SCOPES,
        "state":         state,
        "access_type":   "offline",
        "prompt":        "select_account",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)

def exchange_code_for_token(code):
    resp = http_requests.post(GOOGLE_TOKEN_URL, data={
        "code":          code,
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    })
    resp.raise_for_status()
    return resp.json()


# ── Pricing helpers ───────────────────────────────────────────
def get_rate(meters):
    if meters <= 19:  return 170
    if meters <= 50:  return 160
    if meters <= 100: return 150
    if meters <= 200: return 140
    return 150

def fmt(n):
    return f"₱{float(n or 0):,.2f}"


# ── Routes — Auth ─────────────────────────────────────────────
@app.route("/login")
def login_page():
    if session.get("user") and is_allowed(session["user"]["email"]):
        return redirect(url_for("index"))
    configured = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
    return render_template("login.html", configured=configured)

@app.route("/auth/google")
def auth_google():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "OAuth not configured.", 500
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return redirect(build_auth_url(state))

@app.route("/auth/callback")
def auth_callback():
    try:
        returned_state = request.args.get("state", "")
        saved_state    = session.pop("oauth_state", None)
        if not saved_state or returned_state != saved_state:
            return render_template("login.html",
                                   error="Session mismatch — please try signing in again.",
                                   configured=True)

        code = request.args.get("code")
        if not code:
            return render_template("login.html",
                                   error="No authorization code received from Google.",
                                   configured=True)

        token_data = exchange_code_for_token(code)
        id_tok = token_data.get("id_token")
        if not id_tok:
            return render_template("login.html",
                                   error="No ID token in Google response.",
                                   configured=True)

        id_info = id_token.verify_oauth2_token(
            id_tok,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )

        email   = id_info.get("email", "")
        name    = id_info.get("name", email.split("@")[0])
        picture = id_info.get("picture", "")

        users = load_users()
        if email not in users:
            auto_allow = bool(OWNER_EMAIL and email == OWNER_EMAIL)
            users[email] = {
                "email": email, "name": name, "picture": picture,
                "admin": auto_allow, "allowed": auto_allow,
            }
        else:
            users[email]["name"]    = name
            users[email]["picture"] = picture
        save_users(users)

        session.permanent = True
        session["user"]   = {"email": email, "name": name, "picture": picture}
        return redirect(url_for("index"))

    except Exception as e:
        return render_template("login.html", error=str(e), configured=True)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ── Routes — Main app ─────────────────────────────────────────
@app.route("/")
@access_required
def index():
    user  = session["user"]
    admin = is_admin(user["email"])
    return render_template("index.html", user=user, admin=admin)


# ── Routes — Google Sheets sync ───────────────────────────────
@app.route("/api/sheet-customers")
@access_required
def sheet_customers():
    """
    Reads your DTF Google Sheet (CSV export) and returns rows as JSON.
    The sheet must be shared as 'Anyone with the link can view'.

    Expected columns (row 1 = headers):
      Name | Date | Meters | Rate | Total | Status
    Column names are flexible — we match by index position (A=0, B=1 …)
    or by header name (case-insensitive).
    """
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/export?format=csv&gid={SHEET_GID}"
    )
    try:
        resp = http_requests.get(csv_url, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not fetch sheet: {e}"}), 502

    import csv, io
    rows = list(csv.reader(io.StringIO(resp.text)))
    if not rows:
        return jsonify({"ok": True, "customers": []})

    # Detect headers
    headers = [h.strip().lower() for h in rows[0]]

    def col(row, *names):
        """Return first matching column value, or '' if not found."""
        for n in names:
            if n in headers:
                idx = headers.index(n)
                if idx < len(row):
                    return row[idx].strip()
        return ""

    customers = []
    seen_names = {}   # name → list index in customers

    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue  # skip blank rows

        name   = col(row, "name", "customer", "client")
        date   = col(row, "date", "order date", "orderdate")
        meters = col(row, "meters", "qty", "quantity", "m")
        rate   = col(row, "rate", "price", "rate/m")
        total  = col(row, "total", "amount", "total amount")
        status = col(row, "status", "payment", "paid")

        if not name:
            continue

        # Try to parse numbers
        try:   meters_f = float(meters.replace(",", "")) if meters else 0
        except: meters_f = 0
        try:   rate_f = float(rate.replace(",", "").replace("₱", "")) if rate else 0
        except: rate_f = 0
        try:   total_f = float(total.replace(",", "").replace("₱", "")) if total else meters_f * rate_f
        except: total_f = meters_f * rate_f

        # Normalise status: 'pd' = paid, '' = unpaid
        status_norm = "pd" if status.lower() in ("pd", "paid", "yes", "✓", "p") else ""

        order = {
            "date":   date,
            "qty":    meters_f,
            "rate":   rate_f,
            "total":  total_f,
            "status": status_norm,
        }

        if name in seen_names:
            customers[seen_names[name]]["orders"].append(order)
            customers[seen_names[name]]["total"]  += total_f
            if not status_norm:
                customers[seen_names[name]]["unpaid"] += total_f
            if date > customers[seen_names[name]]["lastDate"]:
                customers[seen_names[name]]["lastDate"] = date
        else:
            seen_names[name] = len(customers)
            customers.append({
                "name":     name,
                "total":    total_f,
                "unpaid":   total_f if not status_norm else 0,
                "orders":   len([order]),   # will count properly below
                "lastDate": date,
                "_orders":  [order],        # raw list for frontend
            })

    # Finalise order counts
    for c in customers:
        c["orders"] = len(c.get("_orders", []))
        c["dtfRows"] = c.pop("_orders", [])

    return jsonify({"ok": True, "customers": customers})


# ── Routes — Current user info ────────────────────────────────
@app.route("/api/me")
@login_required
def api_me():
    user  = session["user"]
    admin = is_admin(user["email"])
    return jsonify({
        "email":   user["email"],
        "name":    user["name"],
        "picture": user.get("picture", ""),
        "admin":   admin,
    })


# ── Routes — Admin panel ──────────────────────────────────────
@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    user  = session["user"]
    users = load_users()
    return render_template("admin.html", user=user, users=users, owner_email=OWNER_EMAIL)

@app.route("/admin/user/allow", methods=["POST"])
@login_required
@admin_required
def admin_allow_user():
    data  = request.json or {}
    email = data.get("email", "").strip().lower()
    allow = bool(data.get("allow", True))
    if not email:
        return jsonify({"ok": False, "msg": "No email"}), 400
    users = load_users()
    if email not in users:
        users[email] = {"email": email, "name": email, "admin": False, "allowed": allow}
    else:
        users[email]["allowed"] = allow
    save_users(users)
    return jsonify({"ok": True})

@app.route("/admin/user/admin", methods=["POST"])
@login_required
@admin_required
def admin_set_admin():
    data   = request.json or {}
    email  = data.get("email", "").strip().lower()
    is_adm = bool(data.get("admin", False))
    if not email or email == OWNER_EMAIL:
        return jsonify({"ok": False, "msg": "Cannot modify owner"}), 400
    users = load_users()
    if email in users:
        users[email]["admin"] = is_adm
        save_users(users)
    return jsonify({"ok": True})

@app.route("/admin/user/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user():
    data  = request.json or {}
    email = data.get("email", "").strip().lower()
    if not email or email == OWNER_EMAIL:
        return jsonify({"ok": False, "msg": "Cannot delete owner"}), 400
    users = load_users()
    users.pop(email, None)
    save_users(users)
    return jsonify({"ok": True})

@app.route("/admin/user/add", methods=["POST"])
@login_required
@admin_required
def admin_add_user():
    data   = request.json or {}
    email  = data.get("email", "").strip().lower()
    name   = data.get("name", email).strip()
    is_adm = bool(data.get("admin", False))
    if not email:
        return jsonify({"ok": False, "msg": "Email required"}), 400
    users = load_users()
    if email not in users:
        users[email] = {"email": email, "name": name, "admin": is_adm, "allowed": True}
    else:
        users[email]["allowed"] = True
        users[email]["admin"]   = is_adm
    save_users(users)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
