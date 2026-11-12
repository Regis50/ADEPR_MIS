"""
sheets_reader.py — Optional Google Sheets reader.
Mirrors the reference version (uses requests to dodge SSL issues, accepts any
tab name). Active ONLY when a credentials.json file is present in this folder;
otherwise the app falls back to local JSON storage in data/.

Setup (to enable Google Sheets sync):
  1. Create a Google Service Account and download the JSON key.
  2. Save it as credentials.json in this folder.
  3. Share the target Google Spreadsheet with the service account email.
  4. Set SHEET_ID below (or via env var ADEPR_SHEET_ID).
"""

import os
import requests
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
SHEET_ID = os.environ.get("ADEPR_SHEET_ID", "1fZLm1HjlfFOb7dbFA5xxXcVb03vCjaA__XgVBaf7xCQ")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

_credentials = None
_session = None


def credentials_present():
    return os.path.exists(CREDENTIALS_FILE)


def _initialize_google_client():
    global _credentials, _session
    if _session is not None:
        return
    print("🔄 Connecting to Google Sheets...")
    _credentials = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    _session = requests.Session()
    _credentials.refresh(Request(session=_session))
    print("✅ Connected to Google Sheets API!")


def read_as_table(tab_name: str, header_row: int = 0, data_start_row: int = 1):
    """Return a pandas DataFrame for the given tab. Returns empty DataFrame on error."""
    import pandas as pd
    if not credentials_present():
        return pd.DataFrame()
    _initialize_google_client()
    range_name = f"'{tab_name}'"
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_name}"
    headers = {
        "Authorization": f"Bearer {_credentials.token}",
        "Content-Type": "application/json",
    }
    try:
        r = _session.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        values = r.json().get("values", [])
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return pd.DataFrame()
    if not values:
        return pd.DataFrame()
    width = max(len(row) for row in values)
    raw_header = list(values[header_row]) if header_row < len(values) else []
    header, seen = [], {}
    for i, name in enumerate(raw_header):
        name = str(name).strip() or f"col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        header.append(name)
    header += [f"col_{i}" for i in range(len(header), width)]
    data = [list(row) + [""] * (width - len(row)) for row in values[data_start_row:]]
    df = pd.DataFrame(data, columns=header)
    df = df[df.apply(lambda r: any(str(c).strip() for c in r), axis=1)]
    return df.reset_index(drop=True)


def sync_from_sheets():
    """
    Pull the live 'incamake yicyumweru' tab and update local churches.json.
    Only used when credentials.json is present and the parish pastor clicks
    "Sync Google Sheet" in the UI. Returns the count of synced churches.
    """
    if not credentials_present():
        return {"ok": False, "error": "credentials.json not found"}
    df = read_as_table("incamake yicyumweru", 2, 4)
    if df.empty:
        return {"ok": False, "error": "no data"}
    # Map columns to churches
    imported = []
    for _, row in df.iterrows():
        name = str(row.get("ITORERO", "")).strip()
        if not name:
            continue
        total = row.get("AMATURO YOSE", 0)
        leader = str(row.get("AMAZINA Y'UMUYOBOZI", "")).strip()
        phone = str(row.get("TELEPHONE", "")).strip()
        existing = next((c for c in __import__("db").list_churches()
                         if c.get("name", "").lower() == name.lower()), None)
        if existing:
            __import__("db").update_church(existing["id"], {
                "leader_name": leader, "leader_phone": phone,
            })
        else:
            c = __import__("db").insert_church({
                "name": name, "parish": "RUHANGO",
                "leader_name": leader, "leader_phone": phone,
            })
            imported.append(c)
    return {"ok": True, "imported": len(imported), "total_synced": len(df)}


if __name__ == "__main__":
    if credentials_present():
        print(sync_from_sheets())
    else:
        print("No credentials.json — sync disabled.")
