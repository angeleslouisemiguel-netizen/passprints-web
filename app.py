"""
PassPrint DTF CRM — Flask + Gemini AI backend
Run:  pip install flask google-generativeai openpyxl
      python app.py
Then open http://localhost:5000
"""

import os, json, re
from flask import Flask, render_template, request, jsonify, session
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dtf-crm-secret-2026")

# ── Gemini setup ──────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")   # set your key here or in env

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
else:
    gemini_model = None

# ── Pricing tiers ─────────────────────────────────────────────
def get_rate(meters: float) -> int:
    if meters <= 19:  return 170
    if meters <= 50:  return 160
    if meters <= 100: return 150
    if meters <= 200: return 140
    return 150   # 201m+

def get_tier_label(m: float) -> str:
    if m <= 9:   return "1–9m (₱170/m)"
    if m <= 19:  return "10–19m (₱170/m)"
    if m <= 50:  return "20–50m (₱160/m)"
    if m <= 100: return "51–100m (₱150/m)"
    if m <= 200: return "101–200m (₱140/m)"
    return "201m+ (₱150/m)"

def fmt(n: float) -> str:
    return f"₱{float(n or 0):,.2f}"

# ── Agent system prompts ───────────────────────────────────────
AGENT_SYSTEM_PROMPTS = {
    "expense": """You are the DTF Expense Logger for passprints., a DTF film printing business in the Philippines.
Your job: parse what the user spent and confirm it in a structured log format.
Extract: category (Materials/Utilities/Supplies/Rent/Delivery), amount (in ₱), date.
Always reply in a short, structured way. End with a brief tip or follow-up question.
Be friendly and helpful. Respond in the same language the user writes (English/Filipino/Taglish).""",

    "quote": """You are the DTF Quote Builder for passprints., a DTF film printing business in the Philippines.
Pricing tiers: 1–19m = ₱170/m, 20–50m = ₱160/m, 51–100m = ₱150/m, 101–200m = ₱140/m, 201m+ = ₱150/m.
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
Pricing: 1–19m=₱170/m, 20–50m=₱160/m, 51–100m=₱150/m, 101–200m=₱140/m, 201m+=₱150/m.
Bank details: BPI 9929260433, BDO 005520304611, GCash 0956-832-0608 (JOEMAREY S. PASAFORTE).
When given meters or amount, generate a clean receipt format including receipt number, date, customer, line items, total, and payment info.
Keep it concise and professional.""",

    "report": """You are the Business Analyst agent for passprints., a DTF film printing business in the Philippines.
You have access to the user's sales data (provided in context).
Analyze the data, spot trends, identify top clients, flag unpaid balances, and give actionable business tips.
Be concise, insightful, and data-driven. Respond in English.""",
}

# ── Flask routes ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    """Handle AI agent messages via Gemini."""
    data = request.json or {}
    agent_type  = data.get("agent", "report")
    user_msg    = data.get("message", "").strip()
    customer    = data.get("customer", "")
    dtf_data    = data.get("dtfData", [])      # full orders list from frontend
    clients     = data.get("clients", [])       # client summary list
    history     = data.get("history", [])       # prior chat turns [{"role":..,"text":..}]

    if not user_msg:
        return jsonify({"reply": "Please type a message."}), 400

    if not gemini_model:
        return jsonify({"reply": "⚠️ Gemini API key not configured. Set GEMINI_API_KEY environment variable."}), 200

    # Build context for the agent
    system_prompt = AGENT_SYSTEM_PROMPTS.get(agent_type, AGENT_SYSTEM_PROMPTS["report"])

    # Add data context
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
            if cust_orders:
                context_lines.append(f"  Order history (latest first):")
                for r in sorted(cust_orders, key=lambda x: x.get("date",""), reverse=True)[:5]:
                    context_lines.append(f"    • {r.get('date')} — {r.get('qty')}m @ ₱{r.get('rate')}/m = {fmt(r.get('total', 0))} ({'Paid' if r.get('status') == 'pd' else 'Unpaid'})")
    elif dtf_data:
        total_rev    = sum(r.get("total", 0) for r in dtf_data if r.get("status") == "pd")
        total_unpaid = sum(r.get("total", 0) for r in dtf_data if not r.get("status"))
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
        # Build Gemini chat with history
        chat_session = gemini_model.start_chat(history=[])

        # Construct messages: system + history + user
        full_history = []
        for turn in history[-6:]:   # last 3 pairs max to stay concise
            role = "user" if turn.get("role") == "user" else "model"
            full_history.append({"role": role, "parts": [turn.get("text", "")]})

        # Re-start with real history
        chat_session = gemini_model.start_chat(history=full_history)

        full_prompt = f"{system_prompt}\n\n---\nUser message: {user_msg}"
        response = chat_session.send_message(full_prompt)
        reply = response.text.strip()
        return jsonify({"reply": reply})

    except Exception as e:
        print(f"Gemini error: {e}")
        return jsonify({"reply": f"⚠️ AI error: {str(e)}"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
