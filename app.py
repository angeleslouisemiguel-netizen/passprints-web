"""
PassPrint DTF CRM — Flask + Gmail OAuth + Google Sheets
Features:
• Gmail OAuth2 login — session persists across refreshes
• Admin panel — owner can whitelist users and grant admin rights
• Google Sheets integration — live data from your spreadsheet
• All original CRM features intact

Setup:
1. pip install -r requirements.txt
2. Create Google OAuth credentials at console.cloud.google.com
3. Copy .env.example → .env and fill in values
4. python app.py
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
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "824885091219-tkbocj406dtdktudmrldiq71ba60kj78.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "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")
REDIRECT_URI         = os.environ.get("REDIRECT_URI", "https://passprint-dtf.onrender.com/auth/callback")

# ── Google Sheets config ──────────────────────────────────────
# Paste your Google Sheet ID here (from the URL: .../d/SHEET_ID/edit)
SHEET_ID             = os.environ.get("SHEET_ID", "")
# Your sheet must be shared as "Anyone with the link can VIEW"
# Tab names to pull data from (must match exactly in your spreadsheet)
DTF_SHEET_TAB        = os.environ.get("DTF_SHEET_TAB", "DTF RECEIVE2026")
EXPENSES_SHEET_TAB   = os.environ.get("EXPENSES_SHEET_TAB", "DTF EXPENSES2026")
SIGNAGE_SHEET_TAB    = os.environ.get("SIGNAGE_SHEET_TAB", "SIGNAGE RECEIVE2026")
SUMMARY_SHEET_TAB    = os.environ.get("SUMMARY_SHEET_TAB", "SUMMARY 2025")

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

# ── Google Sheets helper ──────────────────────────────────────
def fetch_sheet_data(tab_name):
    """Fetch a sheet tab as JSON via the public Sheets API (no auth needed for public sheets)."""
    if not SHEET_ID:
        return []
    try:
        encoded_tab = urllib.parse.quote(tab_name)
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:json&sheet={encoded_tab}"
        resp = http_requests.get(url, timeout=10)
        resp.raise_for_status()
        # Strip the Google wrapper: /*O_o*/\ngoogle.visualization.Query.setResponse({...});
        raw = resp.text
        start = raw.index('{')
        end   = raw.rindex('}') + 1
        data  = json.loads(raw[start:end])
        rows  = []
        cols  = [c.get("label", c.get("id", "")) for c in data["table"]["cols"]]
        for row in data["table"]["rows"]:
            if row is None:
                continue
            record = {}
            for i, cell in enumerate(row["c"]):
                col = cols[i] if i < len(cols) else f"col{i}"
                record[col] = cell["v"] if cell and cell.get("v") is not None else ""
            rows.append(record)
        return rows
    except Exception as e:
        print(f"Sheets fetch error ({tab_name}): {e}")
        return []

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
        return "OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", 500
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

        session.permanent  = True
        session["user"]    = {"email": email, "name": name, "picture": picture}
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

# ── Routes — Google Sheets API ────────────────────────────────
@app.route("/api/sheets/dtf")
@access_required
def api_sheets_dtf():
    """Return DTF receive data from Google Sheets."""
    rows = fetch_sheet_data(DTF_SHEET_TAB)
    return jsonify({"ok": True, "data": rows, "tab": DTF_SHEET_TAB})

@app.route("/api/sheets/expenses")
@access_required
def api_sheets_expenses():
    """Return DTF expenses data from Google Sheets."""
    rows = fetch_sheet_data(EXPENSES_SHEET_TAB)
    return jsonify({"ok": True, "data": rows, "tab": EXPENSES_SHEET_TAB})

@app.route("/api/sheets/signage")
@access_required
def api_sheets_signage():
    """Return signage receive data from Google Sheets."""
    rows = fetch_sheet_data(SIGNAGE_SHEET_TAB)
    return jsonify({"ok": True, "data": rows, "tab": SIGNAGE_SHEET_TAB})

@app.route("/api/sheets/summary")
@access_required
def api_sheets_summary():
    """Return monthly summary data from Google Sheets."""
    rows = fetch_sheet_data(SUMMARY_SHEET_TAB)
    return jsonify({"ok": True, "data": rows, "tab": SUMMARY_SHEET_TAB})

@app.route("/api/sheets/all")
@access_required
def api_sheets_all():
    """Return all sheet data in one call."""
    return jsonify({
        "ok":      True,
        "dtf":     fetch_sheet_data(DTF_SHEET_TAB),
        "expenses":fetch_sheet_data(EXPENSES_SHEET_TAB),
        "signage": fetch_sheet_data(SIGNAGE_SHEET_TAB),
        "summary": fetch_sheet_data(SUMMARY_SHEET_TAB),
    })

@app.route("/api/sheets/config")
@access_required
def api_sheets_config():
    """Return sheet configuration so the frontend knows what's connected."""
    return jsonify({
        "ok":          True,
        "connected":   bool(SHEET_ID),
        "sheet_id":    SHEET_ID[:8] + "..." if SHEET_ID else "",
        "tabs": {
            "dtf":      DTF_SHEET_TAB,
            "expenses": EXPENSES_SHEET_TAB,
            "signage":  SIGNAGE_SHEET_TAB,
            "summary":  SUMMARY_SHEET_TAB,
        }
    })

# ── Routes — Current user info ────────────────────────────────
@app.route("/api/me")
@login_required
def api_me():
    user  = session["user"]
    admin = is_admin(user["email"])
    return jsonify({"email": user["email"], "name": user["name"],
                    "picture": user.get("picture",""), "admin": admin})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
