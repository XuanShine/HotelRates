# %%
import yaml
import pandas as pd
import numpy as np
import gspread
from random import choice
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from sheet import spreadsheet as ss
from datetime import date
pd.set_option('future.no_silent_downcasting', True)
import os
# Get the folder where this script is located
base_dir = os.path.dirname(os.path.abspath(__file__))

def load_config(sheet_key):
    WORKSHEET = ss.client.open_by_key(sheet_key).worksheet("config")
    df = get_as_dataframe(WORKSHEET, index_col=0, skip_blank_lines=True, evaluate_formulas=True, dtype={'value': object})
    # config['value'] = config["value"].astype('object')
    return df

def reset_update_go(config):
    config.loc["update_go", "value"] = False

def export_config(sheet_key, df):
    WORKSHEET = ss.client.open_by_key(sheet_key).worksheet("config")
    set_with_dataframe(
        WORKSHEET,
        df,
        include_index=True
    )


if __name__ == "__main__":
    config = load_config("10vet57RQGSTB2SLOLhwJPehER9nU6gixURsYHv6NULU")
    if config.loc["update_go", "value"]:
        reset_update_go(config)
        export_config(config)
