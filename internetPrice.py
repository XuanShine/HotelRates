# %%
import sys, os

C = os.path.abspath(os.path.dirname(__file__))

import numpy as np
import pandas as pd
from functools import reduce
from datetime import date
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from sheet import spreadsheet as ss
from datetime import timedelta

from wubook_api import get_avail, REAL_ROOMS, upload_prices, room_to_code

WORKSHEET2 = ss.client.open("Prix Aroma").worksheet("Feuille2")

MIN_PRICE = 45

def load_df2():
    df = get_as_dataframe(WORKSHEET2, index_col=0, parse_dates=True, dayfirst=True, skip_blank_lines=True, evaluate_formulas=True)
    return df

# %%
def upload_prices_df(df):
    df = df.copy()
    df[df < 45] = 45
    room_existant = df.columns.intersection(list(room_to_code.keys()))
    df = df[room_existant].rename(columns=room_to_code)
    today = pd.Timestamp.now().date()
    df = df[today:]
    upload_prices(today.strftime("%d/%m/%Y"), df.to_dict("list"))


if __name__ == "__main__":
    df = load_df2()
    upload_prices_df(df)


