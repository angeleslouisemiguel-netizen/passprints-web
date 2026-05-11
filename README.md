# passprints. DTF CRM — Flask + Gemini AI

Full-featured DTF print shop CRM with real Gemini AI agents.

## Quick Start (Local)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your Gemini API key
#    Get a free key at: https://aistudio.google.com/app/apikey
export GEMINI_API_KEY="your-key-here"      # Mac/Linux
set GEMINI_API_KEY=your-key-here           # Windows CMD

# 3. Run the app
python app.py

# 4. Open browser
open http://localhost:5000
```

## Deploy Online (Free Options)

### Option A — Railway (Recommended, 5 min)
1. Push this folder to a GitHub repo
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add environment variable: `GEMINI_API_KEY = your-key`
4. Done — Railway auto-detects Flask!

### Option B — Render
1. Push to GitHub
2. https://render.com → New Web Service → connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `python app.py`
5. Add env var: `GEMINI_API_KEY`

### Option C — Replit
1. Upload files to https://replit.com → New Python repl
2. Add `GEMINI_API_KEY` in Secrets tab
3. Click Run

### Option D — Google Cloud Run / Heroku
Add a `Procfile`:
```
web: python app.py
```
Set `PORT` env var (Flask reads it automatically).

## Project Structure
```
passprints_dtf/
├── app.py                  ← Flask backend + Gemini AI logic
├── requirements.txt        ← Python dependencies
├── README.md
└── templates/
    └── index.html          ← Full CRM frontend (all CSS/JS included)
```

## AI Agents (now powered by Gemini)

| Agent | What it does |
|-------|-------------|
| 💸 Expense Logger | Parse & log DTF material/utility costs |
| 📄 DTF Quote Builder | Auto-calculate quotes by meters + pricing tier |
| 🔔 Payment Chaser | Draft follow-up messages for unpaid customers |
| 🧾 Receipt Generator | Generate formatted receipts with bank details |
| 📊 Business Analyst | Analyze sales data, trends, and customer insights |

All agents receive your live CRM data as context — no dummy data.

## Getting a Gemini API Key (Free)
1. Go to https://aistudio.google.com/app/apikey
2. Sign in with Google
3. Click "Create API Key"
4. Copy and set as `GEMINI_API_KEY`

The free tier is generous — more than enough for a small print shop.
