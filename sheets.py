"""
sheets.py — Google Sheets integration for passprints.
Drop this file in the same folder as app.py.

Actual sheet tab: DTF RECEIVE2026
Headers on row 3: DATE | CUSTOMER | QTY | AMOUNT | TOTAL | STATUS
Data starts row 4 onward.
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SHEET_ID = os.environ.get('GOOGLE_SHEET_ID', '')

_client_cache = None


def _get_client():
    global _client_cache
    if _client_cache:
        return _client_cache
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    _client_cache = gspread.authorize(creds)
    return _client_cache


def get_orders_sheet():
    client = _get_client()
    return client.open_by_key(SHEET_ID).worksheet('DTF RECEIVE2026')


def load_all_data():
    """
    Reads DTF RECEIVE2026 tab.
    Auto-detects the header row containing DATE and CUSTOMER.
    Returns { 'orders': [...], 'customers': [] }
    """
    orders = []

    try:
        sheet = get_orders_sheet()
        all_values = sheet.get_all_values()

        # Find the header row
        header_row_index = None
        for i, row in enumerate(all_values):
            normalized = [str(c).strip().upper() for c in row]
            if 'DATE' in normalized and 'CUSTOMER' in normalized:
                header_row_index = i
                break

        if header_row_index is None:
            print('[sheets] Could not find header row with DATE and CUSTOMER')
            return {'orders': [], 'customers': []}

        headers = [str(c).strip().upper() for c in all_values[header_row_index]]

        def col(name):
            try:
                return headers.index(name)
            except ValueError:
                return None

        date_i     = col('DATE')
        customer_i = col('CUSTOMER')
        qty_i      = col('QTY')
        amount_i   = col('AMOUNT')
        total_i    = col('TOTAL')
        status_i   = col('STATUS')

        def parse_num(val):
            cleaned = str(val).replace('₱', '').replace('P', '').replace(',', '').strip()
            try:
                return float(cleaned)
            except Exception:
                return 0.0

        for row in all_values[header_row_index + 1:]:
            if not any(str(c).strip() for c in row):
                continue

            def cell(i):
                if i is None or i >= len(row):
                    return ''
                return str(row[i]).strip()

            name = cell(customer_i)
            if not name:
                continue

            status = cell(status_i).lower()
            status = 'pd' if status in ('pd', 'paid', '1', 'yes') else ''

            orders.append({
                'date':   cell(date_i),
                'name':   name,
                'qty':    parse_num(cell(qty_i)),
                'rate':   parse_num(cell(amount_i)),
                'total':  parse_num(cell(total_i)),
                'status': status
            })

    except Exception as e:
        print(f'[sheets] load orders error: {e}')

    return {'orders': orders, 'customers': []}


def save_all_data(orders, customers):
    """
    Saves orders back to DTF RECEIVE2026.
    Finds the header row automatically and rewrites from there,
    so rows 1-2 (your bank details, etc.) are never touched.
    """
    try:
        sheet = get_orders_sheet()
        all_values = sheet.get_all_values()

        # Find header row (1-based for gspread)
        header_row_1based = None
        for i, row in enumerate(all_values):
            normalized = [str(c).strip().upper() for c in row]
            if 'DATE' in normalized and 'CUSTOMER' in normalized:
                header_row_1based = i + 1
                break

        if header_row_1based is None:
            print('[sheets] Could not find header row to save')
            return

        data_start = header_row_1based + 1
        last_row   = max(len(all_values), data_start + len(orders) + 5)

        # Clear only columns A-F from header row down
        sheet.batch_clear([f'A{header_row_1based}:F{last_row}'])

        # Rewrite header
        sheet.update(
            f'A{header_row_1based}:F{header_row_1based}',
            [['DATE', 'CUSTOMER', 'QTY', 'AMOUNT', 'TOTAL', 'STATUS']],
            value_input_option='RAW'
        )

        # Write data rows
        if orders:
            rows = [
                [o.get('date',''), o.get('name',''), o.get('qty',0),
                 o.get('rate',0), o.get('total',0), o.get('status','')]
                for o in orders
            ]
            sheet.update(
                f'A{data_start}:F{data_start + len(rows) - 1}',
                rows,
                value_input_option='RAW'
            )

    except Exception as e:
        print(f'[sheets] save orders error: {e}')
        raise
