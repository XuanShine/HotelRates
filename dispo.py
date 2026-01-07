import sys, os

C = os.path.abspath(os.path.dirname("__file__"))

import numpy as np
import pandas as pd
from functools import reduce
from datetime import date
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from sheet import spreadsheet as ss
from datetime import timedelta
from utils import load_df
from loguru import logger

from wubook_api import get_avail, REAL_ROOMS

def export_dispo(sheet_key, df):
    WORKSHEET = ss.client.open_by_key(sheet_key).worksheet("Feuille1")
    headers = WORKSHEET.row_values(1)
    try:
        col_index = headers.index("Libre") + 1
    except ValueError:
        logger.error(f"Column Libre not found in the Sheet!")
    df_subset = df[["Libre"]]
    set_with_dataframe(
        WORKSHEET, 
        df_subset, 
        row=1, 
        col=col_index, 
        include_index=False, 
        resize=False
    )


def get_df_dispo():
    """index: pd.date
    Colonne: "Total"
    """
    today = date.today()
    years2 = date.today() + timedelta(days=729)
    disponibilite_brut = get_avail(today.strftime("%d/%m/%Y"), years2.strftime("%d/%m/%Y"))
    # exclure/filtrer les entrées vides avant de construire le DataFrame,
    # ou s’assurer que chaque valeur est une Series non vide
    # (ou fournir explicitement les dtypes).
    if isinstance(disponibilite_brut, dict):
        disponibilite_brut = {
            k: v for k, v in disponibilite_brut.items()
            if v is not None and not (hasattr(v, "__len__") and len(v) == 0)
        }
    df_dispo = pd.DataFrame(disponibilite_brut).T
    df_dispo.index = pd.to_datetime(df_dispo.index, dayfirst=True)
    df_dispo["Total"] = df_dispo[list(REAL_ROOMS)].sum(axis=1)
    return df_dispo

def add_dispo_to_df(df, df_dispo, df_entete="Libre", df_dispo_entete="Total"):
    df[df_entete] = df_dispo[df_dispo_entete].combine_first(df[df_entete])
    return df

if __name__ == "__main__":
    df_dispo = get_df_dispo()
    df = load_df()
    df = add_dispo_to_df(df, df_dispo)
    export_dispo(df)
    


