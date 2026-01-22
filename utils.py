import yaml
import pandas as pd
import numpy as np
import gspread
from random import choice
from gspread_dataframe import get_as_dataframe, set_with_dataframe
try:
    from sheet import spreadsheet as ss
except ImportError:
    from .sheet import spreadsheet as ss
try:
    import xotelo
except ImportError:
    from . import xotelo
from datetime import date
pd.set_option('future.no_silent_downcasting', True)
import os

def load_df(sheet_key, worksheet="Feuille1") -> pd.DataFrame:
    """
    Raises:
        ConnectionError: En cas d'échec de résolution DNS ou de connexion aux API Google.
    """
    try:
        WORKSHEET = ss.client.open_by_key(sheet_key).worksheet(worksheet)
    except gspread.exceptions.APIError as e:
        raise ConnectionError(e)
    df = get_as_dataframe(WORKSHEET, index_col=0, parse_dates=True, dayfirst=True, skip_blank_lines=True, evaluate_formulas=True)
    return df

def clean_past(df):
    # TODO : le clean past doit aussi ajouter des dates
    df = df[pd.Timestamp.now().date():]
    return df

def export_all_df(sheet_key, df, worksheet="Feuille1"):
    WORKSHEET = ss.client.open_by_key(sheet_key).worksheet(worksheet)
    df_export = df.copy()
    df_export.index = df_export.index.strftime('%d/%m/%Y')
    set_with_dataframe(
        WORKSHEET, 
        df_export, 
        include_index=True,
        resize=True
    )

if __name__ == "__main__":
    sheet_key = "10vet57RQGSTB2SLOLhwJPehER9nU6gixURsYHv6NULU"
    df = load_df(sheet_key)
    df = clean_past(df)
    export_all_df(sheet_key, df)
