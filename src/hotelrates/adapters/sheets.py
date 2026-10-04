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

# Fallback when GOOGLE_SHEET_CREDENTIALS_JSON is unset (legacy split env).
_SERVICE_ACCOUNT_META = {
    "type": "service_account",
    "project_id": "operation-300",
    "private_key_id": "909975fa4d7e452f97f51c2fde66514d54476d78",
    "client_email": "paulxuan@operation-300.iam.gserviceaccount.com",
    "client_id": "105205709115878599213",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/paulxuan%40operation-300.iam.gserviceaccount.com",
}


def _service_account_info():
    raw = os.getenv("GOOGLE_SHEET_CREDENTIALS_JSON")
    if raw:
        return json.loads(raw)
    info = dict(_SERVICE_ACCOUNT_META)
    info["private_key"] = os.getenv("GOOGLE_SHEET_PRIVATE_KEY")
    return info


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
