from random import randrange
import schedule
import time
import functools
import threading
import os, sys
import yaml

from veille_competitive import RandomMode
import veille_competitive
import internetPrice
import dispo
import price
import config
import utils

from loguru import logger
C = os.path.abspath(os.path.dirname(__file__))

# Configuration du fichier de log
# logger.add(
#     os.path.join(C, "logs", "hotelrates.log"),  # Chemin du fichier
#     rotation="10 MB",          # Nouveau fichier quand il atteint 10 Mo
#     retention="10 days",       # Supprime les logs vieux de plus de 10 jours
#     level="INFO"               # Ne note pas les "DEBUG", seulement INFO et plus grave
# )

# logger.add(
#     os.path.join(C, "logs", "hotelrates.log"),  # Chemin du fichier
#     rotation="10 MB",          # Nouveau fichier quand il atteint 10 Mo
#     retention="10 days",       # Supprime les logs vieux de plus de 10 jours
#     level="DEBUG"               # Ne note pas les "DEBUG", seulement INFO et plus grave
# )
# Pour Docker
def setup_logging():
    # 1. On supprime le handler par défaut (qui écrit sur stderr avec un format générique)
    logger.remove()

    # 2. On récupère le niveau de log via une variable d'environnement (défaut: INFO)
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # 4. On ajoute un handler pour écrire dans un fichier
    log_file = os.path.join(C, "logs", "hotelrates.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger.add(
        log_file,
        rotation="10 MB",
        retention="10 days",
        level="DEBUG",
        encoding="utf-8",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        delay=False,
        colorize=True,
    )
    
    # 3. On ajoute un handler propre sur la sortie standard (STDOUT)
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
        enqueue=True  # Important pour Docker : gère les logs de manière asynchrone (thread-safe)
    )



# --- The Parallel Wrapper ---
def run_threaded(job_func):
    job_thread = threading.Thread(target=job_func)
    job_thread.start()

# Decorator to catch errors
# On va utiliser logger.catch
# def catch_exceptions(job_func):
#     @functools.wraps(job_func)
#     def wrapper(*args, **kwargs):
#         try:
#             return job_func(*args, **kwargs)
#         except Exception as e:
#             import traceback
#             logger.error(f"Error in {job_func.__name__}: {e}")
#             traceback.print_exc() # Uncomment to see full error details
#     return wrapper


@logger.catch
def schedule_fill_one_missing_price_random(sheet_key):
    logger.info(f"fill_one_missing_price_random... (key:{sheet_key})")
    df, trip_key = veille_competitive.load_df_and_concurrents(sheet_key)
    veille_competitive.fill_one_missing_price(df, trip_key, random=True)
    veille_competitive.export_df(sheet_key, df, trip_key)
    logger.info("fill_one_missing_price_random... DONE")

@logger.catch
def schedule_correct_price_random(sheet_key):
    logger.info(f"correct_price_random... (key:{sheet_key})")
    df, trip_key = veille_competitive.load_df_and_concurrents(sheet_key)
    if (r := randrange(0, 3)) == 0:  # 1 chance sur 3 de remplir un prix manquant
        veille_competitive.correct_price_random(df, trip_key, randomMode=RandomMode.EXPONENTIAL)
    elif r == 1:
        veille_competitive.correct_price_random(df, trip_key, randomMode=RandomMode.LINEAR)
    else:
        veille_competitive.correct_price_random(df, trip_key, randomMode=RandomMode.NONE)
    veille_competitive.export_df(sheet_key, df, trip_key)
    logger.info("correct_price_random... DONE")
    
@logger.catch
def schedule_fill_one_missing_price(sheet_key):
    logger.info(f"fill_one_missing_price... (key:{sheet_key})")
    df, trip_key = veille_competitive.load_df_and_concurrents(sheet_key)
    veille_competitive.fill_one_missing_price(df, trip_key, random=False)
    veille_competitive.export_df(sheet_key, df, trip_key)
    logger.info("fill_one_missing_price... DONE")

@logger.catch
def schedule_find_price_today(sheet_key):
    logger.info(f"find_price_today... (key: {sheet_key})")
    df, trip_key = veille_competitive.load_df_and_concurrents(sheet_key)
    veille_competitive.find_price(df, trip_key)
    veille_competitive.export_df(sheet_key, df, trip_key)
    logger.info("find_price_today... DONE")


@logger.catch
def yield_revenue(sheet_key):
    # TODO
    logger.info(f"yield_revenue... (key: {sheet_key})")
    # Ajout des dispo
    get_disponibilite(sheet_key)
    
    # Calcul du prix
    df = utils.load_df(sheet_key)
    price.calcul_price_df(df)
    price.export_price(df)
    
    # Mise à jour des prix sur ChannelManager
    upload_price(sheet_key)
    logger.info("yield_revenue... DONE")


@logger.catch
def get_disponibilite(sheet_key):
    # TODO
    logger.info(f"get_disponibilite... (key: {sheet_key})")
    df = utils.load_df(sheet_key)
    df_dispo = dispo.get_df_dispo()
    df = dispo.add_dispo_to_df(df, df_dispo)
    dispo.export_dispo(sheet_key, df)
    logger.info("get_disponibilite... DONE")


@logger.catch
def upload_price(sheet_key):
    # TODO
    logger.info(f"upload_price... (key: {sheet_key})")
    df = internetPrice.load_df2()
    internetPrice.upload_prices_df(df)
    logger.info("upload_price... DONE")
    
@logger.catch
def watch_config(sheet_key, data_client):
    try:
        config_data = config.load_config(sheet_key)
    except ConnectionError as e:
        logger.debug(f"ConnectionError while loading config for key {sheet_key}: {e}")
        logger.info("ConnectionError in run.py , watch_config , skipping this run...")
        return
    if config_data.loc["update_go", "value"]:
        logger.info(f"UPDATE_GO... (key: {sheet_key})")
        
        if data_client.get("veille"):
            schedule_find_price_today(sheet_key)
        if data_client.get("calcul") and data_client.get("channelManager") and data_client.get("dispo"):    
            yield_revenue(sheet_key)
            
        config.reset_update_go(config_data)
        config.export_config(sheet_key, config_data)
        logger.info("UPDATE_GO... DONE")

@logger.catch
def cleanup(sheet_key):
    # TODO: rajouter des dates
    logger.info(f"cleanup... (key: {sheet_key})")
    df = utils.load_df(sheet_key)
    df = utils.clean_past(df)
    utils.export_all_df(sheet_key, df, worksheet="Feuille1")
    logger.info("cleanup... DONE")




def load_clients():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    YAML_CLIENTS = os.path.join(BASE_DIR, 'clients.yml')
    with open(YAML_CLIENTS, "r") as f_in:
        CLIENTS = yaml.safe_load(f_in)
    for name, data_client in CLIENTS.items():
        if data_client.get("veille"):
            schedule.every(7).to(13).minutes.do(schedule_correct_price_random, data_client["key"])
            schedule.every().day.at("01:10").do(schedule_find_price_today, data_client["key"])
            
        if data_client.get("calcul") and data_client.get("channelManager") and data_client.get("dispo"):
            schedule.every(10).minutes.do(yield_revenue, data_client["key"])

        schedule.every(2).minutes.do(watch_config, data_client["key"], data_client)
        schedule.every().day.at("00:05").do(cleanup, data_client["key"])


def main():
    setup_logging()
    logger.info("Before Scheduler")
    load_clients()
    logger.info("Scheduler started...")
    while True:
        # Checks if a task is due
        schedule.run_pending()
        # Wait 1 second to avoid using 100% CPU
        time.sleep(1)
    
if __name__ == "__main__":

    main()