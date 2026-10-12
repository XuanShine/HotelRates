"""Google Sheets adapter: one gspread client, load/export helpers."""
import json
import os

import gspread
import pandas as pd
from dotenv import load_dotenv
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

pd.set_option("future.no_silent_downcasting", True)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _service_account_info():
    raw = os.getenv("GOOGLE_SHEET_CREDENTIALS_JSON")
    if raw:
        return json.loads(raw)
    path = os.getenv("GOOGLE_SHEET_CREDENTIALS_FILE") or os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    raise RuntimeError(
        "Google Sheets credentials are not configured. "
        "Set GOOGLE_SHEET_CREDENTIALS_JSON or GOOGLE_SHEET_CREDENTIALS_FILE."
    )


_creds = ServiceAccountCredentials.from_json_keyfile_dict(_service_account_info(), SCOPES)
client = gspread.authorize(_creds)


def load_df(sheet_key, worksheet="Feuille1"):
    ws = client.open_by_key(sheet_key).worksheet(worksheet)
    return get_as_dataframe(
        ws,
        index_col=0,
        parse_dates=True,
        dayfirst=True,
        skip_blank_lines=True,
        evaluate_formulas=True,
    )


def clean_past(df):
    # TODO : le clean past doit aussi ajouter des dates
    return df[pd.Timestamp.now().date() :]


def export_all_df(sheet_key, df, worksheet="Feuille1"):
    ws = client.open_by_key(sheet_key).worksheet(worksheet)
    df_export = df.copy()
    df_export.index = df_export.index.strftime("%d/%m/%Y")
    set_with_dataframe(
        ws,
        df_export,
        include_index=True,
        resize=True,
    )
