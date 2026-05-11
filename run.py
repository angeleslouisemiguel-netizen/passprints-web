#!/usr/bin/env python3
"""
run.py — Development startup script
Loads .env automatically, then starts Flask.

Usage: python run.py
"""
import os, sys
from pathlib import Path

# Load .env file if present
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    print("✅ Loading .env file...")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
else:
    print("⚠️  No .env file found. Copy .env.example to .env and fill in your values.")
    print("   Running anyway with environment variables...")

# Check critical env vars
missing = []
for var in ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GEMINI_API_KEY", "OWNER_EMAIL"]:
    if not os.environ.get(var):
        missing.append(var)

if missing:
    print(f"\n⚠️  Missing env vars: {', '.join(missing)}")
    print("   Some features may not work. See .env.example for setup.\n")

from app import app
port = int(os.environ.get("PORT", 5000))
print(f"\n🚀 passprints. CRM running at http://localhost:{port}\n")
app.run(debug=True, host="0.0.0.0", port=port)
