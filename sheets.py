"""
sheets.py — Google Sheets integration for passprints.
Drop this file in the same folder as app.py.
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SHEET_ID = os.environ.get('GOOGLE_SHEET_ID', '')  # set this in your .env / Railway env vars

_client_cache = None  # simple module-level cache so we don't re-auth every request


def _get_client():
    global _client_cache
    if _client_cache:
        return _client_cache
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        # Deployed: credentials stored as env var JSON string
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # Local: credentials.json file in project root
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    _client_cache = gspread.authorize(creds)
    return _client_cache


def get_orders_sheet():
    client = _get_client()
    return client.open_by_key(SHEET_ID).worksheet('Orders')


def get_customers_sheet():
    client = _get_client()
    return client.open_by_key(SHEET_ID).worksheet('Customers')


def load_all_data():
    """
    Returns { 'orders': [...], 'customers': [...] }
    Matches exactly what the frontend expects from GET /api/data.
    """
    orders = []
    customers = []

    try:
        sheet = get_orders_sheet()
        rows = sheet.get_all_records()
        for r in rows:
            name = str(r.get('CUSTOMER', '') or '').strip()
            if not name:
                continue
            orders.append({
                'date':   str(r.get('DATE', '') or ''),
                'name':   name,
                'qty':    float(r.get('QTY') or 0),
                'rate':   float(r.get('RATE') or 0),
                'total':  float(r.get('TOTAL') or 0),
                'status': str(r.get('STATUS', '') or '').lower().strip()
            })
    except Exception as e:
        print(f'[sheets] load orders error: {e}')

    try:
        csheet = get_customers_sheet()
        crows = csheet.get_all_records()
        for r in crows:
            name = str(r.get('NAME', '') or '').strip()
            if not name:
                continue
            customers.append({
                'name':  name,
                'phone': str(r.get('PHONE', '') or ''),
                'notes': str(r.get('NOTES', '') or '')
            })
    except Exception as e:
        print(f'[sheets] load customers error: {e}')

    return {'orders': orders, 'customers': customers}


def save_all_data(orders, customers):
    """
    Full sync — rewrites both sheets from the frontend state.
    Called from POST /api/data (debounced 600ms by the frontend).
    """
    # ── Orders sheet ──────────────────────────────────────────
    try:
        sheet = get_orders_sheet()
        sheet.clear()
        sheet.append_row(['DATE', 'CUSTOMER', 'QTY', 'RATE', 'TOTAL', 'STATUS'])
        if orders:
            rows = [
                [o.get('date', ''), o.get('name', ''), o.get('qty', 0),
                 o.get('rate', 0), o.get('total', 0), o.get('status', '')]
                for o in orders
            ]
            sheet.append_rows(rows, value_input_option='RAW')
    except Exception as e:
        print(f'[sheets] save orders error: {e}')
        raise

    # ── Customers sheet ───────────────────────────────────────
    try:
        csheet = get_customers_sheet()
        csheet.clear()
        csheet.append_row(['NAME', 'PHONE', 'NOTES'])
        if customers:
            crows = [
                [c.get('name', ''), c.get('phone', ''), c.get('notes', '')]
                for c in customers
            ]
            csheet.append_rows(crows, value_input_option='RAW')
    except Exception as e:
        print(f'[sheets] save customers error: {e}')
        raise
