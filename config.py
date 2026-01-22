# %%
import yaml
import os
import pandas as pd
import numpy as np
import gspread
import google.auth.exceptions
from random import choice
from gspread_dataframe import get_as_dataframe, set_with_dataframe
try:
    from sheet import spreadsheet as ss
except ImportError:
    from .sheet import spreadsheet as ss
from datetime import date
pd.set_option('future.no_silent_downcasting', True)

# Get the folder where this script is located
base_dir = os.path.dirname(os.path.abspath(__file__))

def load_config(sheet_key) -> pd.DataFrame:
    """
    Charge la configuration dans la feuille de Google Sheets.

    Args:
        sheet_key (str): La clé de la feuille Google Sheet.

    Returns:
        pd.DataFrame: Un DataFrame de la configuration.

    Raises:
        ConnectionError: En cas d'échec de résolution DNS ou de connexion aux API Google.
    """
    try:
        WORKSHEET = ss.client.open_by_key(sheet_key).worksheet("config")
        df = get_as_dataframe(WORKSHEET, index_col=0, skip_blank_lines=True, evaluate_formulas=True, dtype={'value': object})
        # config['value'] = config["value"].astype('object')
        return df
    except google.auth.exceptions.TransportError as e:
        raise ConnectionError(e)

def reset_update_go(config):
    config.loc["update_go", "value"] = False

def export_config(sheet_key, df):
    try:
        WORKSHEET = ss.client.open_by_key(sheet_key).worksheet("config")
        set_with_dataframe(
            WORKSHEET,
            df,
            include_index=True
        )
    except google.auth.exceptions.TransportError as e:
        raise ConnectionError(e)


if __name__ == "__main__":
    config = load_config("10vet57RQGSTB2SLOLhwJPehER9nU6gixURsYHv6NULU")
    if config.loc["update_go", "value"]:
        reset_update_go(config)
        export_config(config)
