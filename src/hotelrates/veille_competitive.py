#!/usr/bin/env python
# coding: utf-8


# TODO : re-vérifier les prix avec un algo et un scraping xotelo avancée (sur plusiers jours)
# TODO : scraper avec booking, expedia, sur le site de l’hôtel, trivago, tripadvisor

import yaml
import pandas as pd
import numpy as np
import gspread
from random import choice
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from .adapters import sheets as ss
from .paths import REPO_ROOT
from .scraper import xotelo
import importlib
from datetime import date
pd.set_option('future.no_silent_downcasting', True)
import os

from loguru import logger


# Get the folder where this script is located
base_dir = os.path.dirname(os.path.abspath(__file__))


def _load_direct_scrapers():
    """Map short name and TripAdvisor id -> scraper module name from hotels.yml `direct`."""
    by_short = {}
    by_trip = {}
    path = os.path.join(REPO_ROOT, "hotels.yml")
    with open(path, "r") as f_in:
        hotels = yaml.safe_load(f_in) or {}
    for data in hotels.values():
        if not isinstance(data, dict):
            continue
        direct = data.get("direct")
        if not direct:
            continue
        module_name = os.path.splitext(os.path.basename(str(direct)))[0]
        if data.get("short"):
            by_short[data["short"]] = module_name
        if data.get("id_tripadvisor"):
            by_trip[str(data["id_tripadvisor"])] = module_name
    return by_short, by_trip


DIRECT_BY_SHORT, DIRECT_BY_TRIP = _load_direct_scrapers()


def _direct_price(module_name, night):
    """Call hotelrates.scraper.<module>.cost(night). 0 if missing or failed."""
    try:
        mod = importlib.import_module(f"hotelrates.scraper.{module_name}")
    except Exception as e:
        logger.warning(f"import scraper {module_name}: {e}")
        return 0
    cost_fn = getattr(mod, "cost", None)
    if cost_fn is None:
        logger.warning(f"{module_name} n'expose pas cost()")
        return 0
    try:
        price = cost_fn(night)
    except Exception as e:
        logger.warning(f"{module_name}.cost a échoué: {e}")
        return 0
    if not price or price is False:
        return 0
    return int(price)


def fetch_price(hotel, tr_key, night):
    """Prix direct (hotels.yml) puis Xotelo si le direct est vide ou en erreur."""
    module_name = DIRECT_BY_SHORT.get(hotel) or DIRECT_BY_TRIP.get(str(tr_key))
    if module_name:
        price = _direct_price(module_name, night)
        if price > 0:
            logger.debug(f"{hotel} via {module_name}: {price}")
            return price
        logger.info(f"{hotel}: {module_name} sans prix, fallback xotelo")
    return xotelo.cost(tr_key, night)


def load_df_and_concurrents(key:str) -> tuple[object, dict]:
    """Load the google sheet, worksheet Feuille1 and configHotelsConcurrents
    The dataframe will be fill with news hotels in configHotelsConcurrents.

    Args:
        key (str): key of the google sheet

    Returns:
        tuple[object, dict]: - Dataframe of the Feuille1
                             - dict {<key>: <name>} of the name of hotel concurrents in configHotelsConcurrents
    """
    WORKSHEET = ss.client.open_by_key(key).worksheet("Feuille1")
    WORKSHEET_HOTELS = ss.client.open_by_key(key).worksheet("configHotelsConcurrents")

    df = get_as_dataframe(WORKSHEET, index_col=0, parse_dates=True, dayfirst=True, skip_blank_lines=True, evaluate_formulas=True)
    # On remplit le tableau avec les hotels qui sont présents dans le worksheet configHotelsConcurrents
    data = WORKSHEET_HOTELS.get_all_values()
    trip_key = {row[0]: row[1] for row in data[1:]}
    
    for hotel in trip_key.keys():
        if hotel not in df.columns:
            df[hotel] = np.nan
            next_col = len(WORKSHEET.row_values(1)) + 1
            WORKSHEET.add_cols(1)
            WORKSHEET.update_cell(1, next_col, hotel)
            
    return df, trip_key

def find_price(df, trip_key, dt_date=None):
    if dt_date == None:
        dt_date = date.today()
    str_date = str(dt_date)
    for hotel, tr_key in trip_key.items():
        logger.debug(f"update {dt_date} {hotel}")
        new_price = fetch_price(hotel, tr_key, dt_date)
        if new_price and new_price > 0:
            df.at[str_date, hotel] = new_price
    return df


def fill_one_missing_price(df, trip_key, random=False):
    today = pd.Timestamp.now().normalize()
    nan_coords = df[today:][list(trip_key.keys())].isna().stack()
    nan_coords = nan_coords[nan_coords].index.tolist()
    if nan_coords:
        if random:
            time, hotel = choice(nan_coords)
        else:
            time, hotel = choice(nan_coords[:10])
        logger.debug(f"update {time}, {hotel}")
        df.loc[time, hotel] = fetch_price(hotel, trip_key[hotel], time) or np.nan
    return df


def update_random_price(df, trip_key, days):
    """Refresh one random competitor price in the next `days` nights (today included)."""
    days = int(days)
    if days < 1:
        logger.warning(f"days must be >= 1, got {days}")
        return df
    today = pd.Timestamp.now().normalize()
    end = today + pd.Timedelta(days=days - 1)
    hotels = list(trip_key.keys())
    window = df.loc[today:end, hotels]
    coords = [(idx, hotel) for idx in window.index for hotel in hotels]
    if not coords:
        logger.info(f"no dates in the next {days} days")
        return df
    time, hotel = choice(coords)
    logger.debug(f"update {time}, {hotel}")
    df.loc[time, hotel] = fetch_price(hotel, trip_key[hotel], time) or np.nan
    return df


def export_df(sheet_key, df, trip_key):
    WORKSHEET = ss.client.open_by_key(sheet_key).worksheet("Feuille1")
    headers = WORKSHEET.row_values(1)
    for hotel in trip_key.keys():
        try:
            col_index = headers.index(hotel) + 1
        except ValueError:
            logger.error(f"Column {hotel} not found in the Sheet!")
            continue
        df_subset = df[[hotel]]
        set_with_dataframe(
            WORKSHEET, 
            df_subset, 
            row=1, 
            col=col_index, 
            include_index=False, 
            resize=False
        )


if __name__ == "__main__":
    sheet_key = "10vet57RQGSTB2SLOLhwJPehER9nU6gixURsYHv6NULU"
    df, trip_key = load_df_and_concurrents(sheet_key)
    find_price(df, trip_key)
    fill_one_missing_price(df, trip_key)
    export_df(sheet_key, df, trip_key)
    
    