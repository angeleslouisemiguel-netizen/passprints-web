"""
PassPrint DTF CRM — Flask + Gmail OAuth + Gemini AI

Features:
• Gmail OAuth2 login — session persists across refreshes
• Admin panel — owner can whitelist users and grant admin rights
• Gemini AI agents — key embedded server-side, never exposed
• JSONBin.io for persistent cloud storage (works on Render free tier)
• All original CRM features intact

Setup:
1. pip install -r requirements.txt
2. Create Google OAuth credentials at console.cloud.google.com
   (Web app, add http://localhost:5000/auth/callback as redirect URI)
3. Create a free bin at jsonbin.io — get your Bin ID and API key
4. Copy .env.example → .env and fill in values
5. python run.py
"""

import os, json, functools, secrets, urllib.parse
from datetime import timedelta
import requests as http_requests
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, abort)
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import google.generativeai as genai

app = Flask(__name__)

# ── Secret key ────────────────────────────────────────────────
# IMPORTANT: set FLASK_SECRET in your .env — never use the default in production
_default_secret = secrets.token_hex(32)  # random per-process fallback
app.secret_key = os.environ.get("FLASK_SECRET") or _default_secret
app.permanent_session_lifetime = timedelta(days=30)

# ── Gemini ────────────────────────────────────────────────────
# FIX: use gemini-2.0-flash — gemini-1.5-flash is no longer available on v1beta
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.0-flash")
else:
    gemini_model = None

# ── Google OAuth config ───────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "824885091219-tkbocj406dtdktudmrldiq71ba60kj78.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "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")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://passprint-dtf.onrender.com/auth/callback")

# ── Owner config ──────────────────────────────────────────────
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")

# ── JSONBin.io config ─────────────────────────────────────────
# Two separate bins — one for login/admin users, one for CRM customer data.
# Create a free account at jsonbin.io, make TWO bins (each starting with {}),
# and set these env vars in Render:
#
#   JSONBIN_API_KEY        — your JSONBin Master Key (same key works for all bins)
#   JSONBIN_USERS_BIN_ID   — Bin ID for users/admin data
#   JSONBIN_CRM_BIN_ID     — Bin ID for orders/customers CRM data

JSONBIN_API_KEY      = os.environ.get("JSONBIN_API_KEY", "")
JSONBIN_USERS_BIN_ID = os.environ.get("JSONBIN_USERS_BIN_ID", "")
JSONBIN_CRM_BIN_ID   = os.environ.get("JSONBIN_CRM_BIN_ID", "")

JSONBIN_USERS_URL = f"https://api.jsonbin.io/v3/b/{JSONBIN_USERS_BIN_ID}" if JSONBIN_USERS_BIN_ID else ""
JSONBIN_CRM_URL   = f"https://api.jsonbin.io/v3/b/{JSONBIN_CRM_BIN_ID}"   if JSONBIN_CRM_BIN_ID   else ""

# Fallback local files (used when JSONBin is not configured — local dev)
USERS_FILE    = os.path.join(os.path.dirname(__file__), "users.json")
CRM_DATA_FILE = os.path.join(os.path.dirname(__file__), "crm_data.json")


# ── JSONBin helpers ───────────────────────────────────────────

def _jb_headers():
    return {
        "Content-Type":     "application/json",
        "X-Master-Key":     JSONBIN_API_KEY,
        "X-Bin-Versioning": "false",  # always overwrite, no version history
    }


def _jb_load(url, label="data"):
    """Load a bin's record dict. Returns {} on any error."""
    try:
        r = http_requests.get(url + "/latest", headers=_jb_headers(), timeout=10)
        r.raise_for_status()
        return r.json().get("record", {})
    except Exception as e:
        print(f"JSONBin load error ({label}): {e}")
        return {}


def _jb_save(url, data, label="data"):
    """Save (overwrite) a bin with data. Logs errors but doesn't raise."""
    try:
        r = http_requests.put(url, json=data, headers=_jb_headers(), timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"JSONBin save error ({label}): {e}")


def _local_load(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _local_save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# ── Users bin (login / admin) ─────────────────────────────────

def load_users():
    """Load users from JSONBin Users bin, or local file in dev."""
    if JSONBIN_USERS_URL and JSONBIN_API_KEY:
        data = _jb_load(JSONBIN_USERS_URL, "users")
        # Auto-seed owner on first load
        if OWNER_EMAIL and OWNER_EMAIL not in data:
            data[OWNER_EMAIL] = {
                "email": OWNER_EMAIL, "name": "Owner",
                "admin": True, "allowed": True
            }
            save_users(data)
        return data
    # Local fallback
    data = _local_load(USERS_FILE)
    if OWNER_EMAIL and OWNER_EMAIL not in data:
        data[OWNER_EMAIL] = {
            "email": OWNER_EMAIL, "name": "Owner",
            "admin": True, "allowed": True
        }
        _local_save(USERS_FILE, data)
    return data


def save_users(data):
    """Save users to JSONBin Users bin, or local file in dev."""
    if JSONBIN_USERS_URL and JSONBIN_API_KEY:
        _jb_save(JSONBIN_USERS_URL, data, "users")
    else:
        _local_save(USERS_FILE, data)


# ── CRM bin (orders / customers) ─────────────────────────────

def load_crm():
    """Load CRM data from JSONBin or local file.
    Returns a dict: {"orders": [...], "customers": [...]}
    """
    if JSONBIN_CRM_URL and JSONBIN_API_KEY:
        data = _jb_load(JSONBIN_CRM_URL, "crm")
    else:
        data = _local_load(CRM_DATA_FILE)

    # Normalise: bin may be seeded as {} or as a bare list (legacy)
    if isinstance(data, list):
        return {"orders": data, "customers": []}
    if isinstance(data, dict):
        return {
            "orders":    data.get("orders",    []),
            "customers": data.get("customers", []),
        }
    return {"orders": [], "customers": []}


def save_crm(payload):
    """Save CRM data. payload must be a dict with 'orders' and 'customers' lists."""
    if not isinstance(payload, dict):
        payload = {"orders": payload, "customers": []}  # legacy list compat
    if JSONBIN_CRM_URL and JSONBIN_API_KEY:
        _jb_save(JSONBIN_CRM_URL, payload, "crm")
    else:
        _local_save(CRM_DATA_FILE, payload)


def get_user(email):
    return load_users().get(email)


def is_allowed(email):
    """User is allowed if they are the owner, or their record has allowed=True."""
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


# ── OAuth flow helper ─────────────────────────────────────────

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
    return 130  # BUG FIX: 201m+ should be cheapest tier (was 150, more expensive than 101-200m tier)


def fmt(n):
    return f"₱{float(n or 0):,.2f}"


# ── Agent system prompts ──────────────────────────────────────

AGENT_SYSTEM_PROMPTS = {
    "expense": """You are the DTF Expense Logger for passprints., a DTF film printing business in the Philippines.
Your job: parse what the user spent and confirm it in a structured log format.
Extract: category (Materials/Utilities/Supplies/Rent/Delivery), amount (in ₱), date.
Always reply in a short, structured way. End with a brief tip or follow-up question.
Be friendly and helpful. Respond in the same language the user writes (English/Filipino/Taglish).""",

    "quote": """You are the DTF Quote Builder for passprints., a DTF film printing business in the Philippines.
Pricing tiers: 1–19m = ₱170/m, 20–50m = ₱160/m, 51–100m = ₱150/m, 101–200m = ₱140/m, 201m+ = ₱130/m.
Bank details: BPI 9929260433, BDO 005520304611, GCash 0956-832-0608 (JOEMAREY S. PASAFORTE).
When the user gives meters, compute the quote and present it clearly with the pricing tier.
Keep replies concise and formatted. Respond in English/Filipino/Taglish as the user prefers.""",

    "followup": """You are the Payment Chaser agent for passprints., a DTF film printing business in the Philippines.
Your job: draft polite but firm follow-up messages for customers with unpaid balances.
Payment options: GCash 0956-832-0608, BPI 9929260433, BDO 005520304611.
Adjust tone (friendly/firm/urgent) based on what the user asks.
Write in English, Filipino, or Taglish depending on user preference.
Keep messages short and professional.""",

    "receipt": """You are the Receipt Generator for passprints., a DTF film printing business in the Philippines.
Pricing: 1–19m=₱170/m, 20–50m=₱160/m, 51–100m=₱150/m, 101–200m=₱140/m, 201m+=₱130/m.
Bank details: BPI 9929260433, BDO 005520304611, GCash 0956-832-0608 (JOEMAREY S. PASAFORTE).
When given meters or amount, generate a clean receipt format including receipt number, date, customer, line items, total, and payment info.
Keep it concise and professional.""",

    "report": """You are the Business Analyst agent for passprints., a DTF film printing business in the Philippines.
You have access to the user's sales data (provided in context).
Analyze the data, spot trends, identify top clients, flag unpaid balances, and give actionable business tips.
Be concise, insightful, and data-driven. Respond in English.""",
}


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
        return "OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file.", 500
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return redirect(build_auth_url(state))


@app.route("/auth/callback")
def auth_callback():
    try:
        # BUG FIX: handle OAuth error param (e.g. user cancels login)
        oauth_error = request.args.get("error")
        if oauth_error:
            msg = "Google sign-in was cancelled." if oauth_error == "access_denied" else f"OAuth error: {oauth_error}"
            return render_template("login.html", error=msg, configured=True)

        # CSRF / state check
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

        # Exchange code → tokens
        token_data = exchange_code_for_token(code)
        id_tok = token_data.get("id_token")
        if not id_tok:
            return render_template("login.html",
                                   error="No ID token in Google response.",
                                   configured=True)

        # Verify the ID token
        id_info = id_token.verify_oauth2_token(
            id_tok,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )

        email   = id_info.get("email", "")
        name    = id_info.get("name", email.split("@")[0])
        picture = id_info.get("picture", "")

        # Store / update user record
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
        session["user"] = {"email": email, "name": name, "picture": picture}
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
    if not email:
        return jsonify({"ok": False, "msg": "Email required"}), 400
    # BUG FIX: owner check was blocking the whole request even for valid users
    if email == OWNER_EMAIL:
        return jsonify({"ok": False, "msg": "Cannot modify owner"}), 400
    users = load_users()
    # BUG FIX: was silently doing nothing if user not in file; now returns error
    if email not in users:
        return jsonify({"ok": False, "msg": "User not found"}), 404
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


# ── Routes — CRM Data (orders / customers) ───────────────────
# The frontend uses /api/data (GET + POST) to load/save both orders and customers.
# /api/crm is kept for backward compatibility.

@app.route("/api/data", methods=["GET"])
@access_required
def api_data_load():
    """Return all orders and customers in one payload.""",
    payload   = load_crm()
    orders    = payload.get("orders",    []) if isinstance(payload, dict) else payload
    customers = payload.get("customers", []) if isinstance(payload, dict) else []
    return jsonify({"ok": True, "orders": orders, "customers": customers})


@app.route("/api/data", methods=["POST"])
@access_required
def api_data_save():
    """Save orders and customers together.""",
    data      = request.json or {}
    orders    = data.get("orders",    [])
    customers = data.get("customers", [])
    if not isinstance(orders, list) or not isinstance(customers, list):
        return jsonify({"ok": False, "msg": "orders and customers must be lists"}), 400
    save_crm({"orders": orders, "customers": customers})
    return jsonify({"ok": True, "saved_orders": len(orders), "saved_customers": len(customers)})


@app.route("/api/crm", methods=["GET"])
@access_required
def api_crm_load():
    """Return orders only (compat).""",
    payload = load_crm()
    orders  = payload.get("orders", []) if isinstance(payload, dict) else payload
    return jsonify({"ok": True, "orders": orders})


@app.route("/api/crm", methods=["POST"])
@access_required
def api_crm_save():
    """Save full order list (compat).""",
    data   = request.json or {}
    orders = data.get("orders", [])
    if not isinstance(orders, list):
        return jsonify({"ok": False, "msg": "orders must be a list"}), 400
    payload = load_crm()
    customers = payload.get("customers", []) if isinstance(payload, dict) else []
    save_crm({"orders": orders, "customers": customers})
    return jsonify({"ok": True, "saved": len(orders)})


@app.route("/api/crm/order", methods=["POST"])
@access_required
def api_crm_add_order():
    """Append a single order record to the CRM list."""
    order = request.json or {}
    if not order:
        return jsonify({"ok": False, "msg": "No order data"}), 400
    orders = load_crm()
    orders.append(order)
    save_crm(orders)
    return jsonify({"ok": True, "total": len(orders)})


@app.route("/api/crm/order/<int:index>", methods=["PUT"])
@access_required
def api_crm_update_order(index):
    """Update a single order by its list index."""
    updated = request.json or {}
    orders = load_crm()
    if index < 0 or index >= len(orders):
        return jsonify({"ok": False, "msg": "Index out of range"}), 404
    orders[index] = updated
    save_crm(orders)
    return jsonify({"ok": True})


@app.route("/api/crm/order/<int:index>", methods=["DELETE"])
@access_required
def api_crm_delete_order(index):
    """Delete a single order by its list index."""
    orders = load_crm()
    if index < 0 or index >= len(orders):
        return jsonify({"ok": False, "msg": "Index out of range"}), 404
    orders.pop(index)
    save_crm(orders)
    return jsonify({"ok": True, "remaining": len(orders)})


# ── Routes — AI Chat ──────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
@access_required
def chat():
    data       = request.json or {}
    agent_type = data.get("agent", "report")
    user_msg   = data.get("message", "").strip()
    customer   = data.get("customer", "")
    dtf_data   = data.get("dtfData", [])
    clients    = data.get("clients", [])
    history    = data.get("history", [])

    if not user_msg:
        return jsonify({"reply": "Please type a message."}), 400

    if not gemini_model:
        return jsonify({"reply": (
            "⚠️ Gemini AI is not configured yet.\n\n"
            "Ask the shop owner to set the GEMINI_API_KEY environment variable.\n"
            "Free key at: https://aistudio.google.com/app/apikey"
        )}), 200

    system_prompt = AGENT_SYSTEM_PROMPTS.get(agent_type, AGENT_SYSTEM_PROMPTS["report"])
    context_lines = []

    if customer and clients:
        client_info = next((c for c in clients if c.get("name") == customer), None)
        if client_info:
            context_lines.append(f"SELECTED CUSTOMER: {customer}")
            context_lines.append(f"  Total revenue: {fmt(client_info.get('total', 0))}")
            context_lines.append(f"  Orders: {client_info.get('orders', 0)}")
            context_lines.append(f"  Unpaid: {fmt(client_info.get('unpaid', 0))}")
            context_lines.append(f"  Last order date: {client_info.get('lastDate', 'N/A')}")
            cust_orders = [r for r in dtf_data if r.get("name") == customer]
            for r in sorted(cust_orders, key=lambda x: x.get("date", ""), reverse=True)[:5]:
                # BUG FIX: was using `not r.get("status")` which incorrectly counts non-"pd" statuses as unpaid
                paid_label = "Paid" if r.get("status") == "pd" else "Unpaid"
                context_lines.append(
                    f"  • {r.get('date')} — {r.get('qty')}m @ ₱{r.get('rate')}/m"
                    f" = {fmt(r.get('total', 0))} ({paid_label})"
                )
    elif dtf_data:
        total_rev    = sum(r.get("total", 0) for r in dtf_data if r.get("status") == "pd")
        # BUG FIX: was `not r.get("status")` — use explicit check so partial payments aren't missed
        total_unpaid = sum(r.get("total", 0) for r in dtf_data if r.get("status") != "pd")
        context_lines.append(f"BUSINESS SNAPSHOT:")
        context_lines.append(f"  Total orders: {len(dtf_data)}")
        context_lines.append(f"  Revenue (paid): {fmt(total_rev)}")
        context_lines.append(f"  Outstanding: {fmt(total_unpaid)}")
        if clients:
            top = sorted(clients, key=lambda c: c.get("total", 0), reverse=True)[:3]
            context_lines.append(f"  Top clients: {', '.join(c['name'] for c in top)}")

    if context_lines:
        system_prompt += "\n\nCURRENT DATA CONTEXT:\n" + "\n".join(context_lines)

    try:
        full_history = []
        for turn in history[-6:]:
            role = "user" if turn.get("role") == "user" else "model"
            full_history.append({"role": role, "parts": [turn.get("text", "")]})

        chat_session = gemini_model.start_chat(history=full_history)
        full_prompt  = f"{system_prompt}\n\n---\nUser message: {user_msg}"
        response     = chat_session.send_message(full_prompt)
        return jsonify({"reply": response.text.strip()})

    except Exception as e:
        print(f"Gemini error: {e}")
        return jsonify({"reply": f"⚠️ AI error: {str(e)}"}), 200


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
