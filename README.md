# passprints. DTF CRM — Flask + Gmail Login + Gemini AI

Full-featured DTF print shop CRM with:
- **Gmail OAuth2 login** — persistent sessions, no password needed
- **Admin panel** — approve users, grant/revoke access and admin rights
- **Gemini AI agents** — key is server-side, never exposed to browser
- **All original CRM features** — dashboard, orders, customers, quotes, receipts

---

## Quick Start (Local)

### Step 1 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 2 — Get a Google OAuth Client ID (free)
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable **Google+ API** or **People API** (under APIs & Services → Library)
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Add authorized redirect URI: `http://localhost:5000/auth/callback`
7. Copy **Client ID** and **Client Secret**

### Step 3 — Get a Gemini API Key (free)
1. Go to https://aistudio.google.com/app/apikey
2. Sign in with Google → Create API Key
3. Copy the key

### Step 4 — Configure your .env
```bash
cp .env.example .env
# Edit .env with your values
```

Fill in:
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
OWNER_EMAIL=your@gmail.com
GEMINI_API_KEY=...
FLASK_SECRET=any-long-random-string
REDIRECT_URI=http://localhost:5000/auth/callback
```

### Step 5 — Run
```bash
python run.py
# Opens at http://localhost:5000
```

First login with your OWNER_EMAIL → you are automatically admin.

---

## Deploy Online (Free)

### Railway (Recommended — 5 min)
1. Push folder to GitHub
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add all env vars (copy from .env)
4. Change `REDIRECT_URI` to `https://your-app.railway.app/auth/callback`
5. Add the same redirect URI to your Google OAuth credentials

### Render
1. Push to GitHub
2. [render.com](https://render.com) → New Web Service → connect repo
3. Start command: `gunicorn app:app`
4. Add all env vars

---

## Admin Panel

Access at `/admin` (only visible to admin users).

| Action | Description |
|--------|-------------|
| **Add User** | Pre-approve a Gmail address before they log in |
| **Allow / Revoke** | Grant or remove CRM access |
| **Make Admin / Unadmin** | Give admin panel access |
| **Delete** | Remove user from the system |

When a new Gmail user logs in for the first time, they see a "Pending" screen. You approve them in the Admin Panel.

---

## AI Agents (Gemini)

| Agent | What it does |
|-------|-------------|
| 💸 Expense Logger | Parse & log DTF material/utility costs |
| 📄 DTF Quote Builder | Auto-calculate quotes by meters + pricing tier |
| 🔔 Payment Chaser | Draft follow-up messages for unpaid customers |
| 🧾 Receipt Generator | Generate formatted receipts with bank details |
| 📊 Business Analyst | Analyze sales data, trends, and customer insights |

All agents receive your live CRM data as context. The API key is stored server-side and never sent to the browser.

---

## Project Structure
```
passprints_dtf/
├── app.py                  ← Flask backend (OAuth + Gemini + Admin)
├── run.py                  ← Dev startup script (auto-loads .env)
├── requirements.txt
├── Procfile                ← For Railway/Heroku
├── .env.example            ← Copy to .env and fill in
├── users.json              ← Auto-created, stores user access list
└── templates/
    ├── index.html          ← Main CRM app
    ├── login.html          ← Gmail sign-in page
    ├── admin.html          ← User management panel
    └── pending.html        ← Shown to unapproved users
```
