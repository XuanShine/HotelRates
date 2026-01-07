import sys, os
import traceback
from datetime import datetime, timedelta, date
import httpx
import time
import numpy as np

from loguru import logger

C = os.path.abspath(os.path.dirname(__file__))
sys.path.append(os.path.join(C, "."))

r = httpx.Client()

def cost(hotel_key, date):
    """date: datetime"""
    url_base = "https://data.xotelo.com/api/rates"
    query = {
        "hotel_key": hotel_key,
        "chk_in": date.strftime("%Y-%m-%d"),
        "chk_out": (date + timedelta(days=1)).strftime("%Y-%m-%d"),
        "currency": "EUR"
    }
    
    try:
        res = r.get(url_base, params=query, timeout=15)
        res.raise_for_status()
        data = res.json()['result']['rates']
    except httpx.HTTPStatusError as e:
        logger.error(f"Erreur HTTP {e.response.status_code} pour l'URL {e.request.url}")
        return 0
    except Exception as e:
        logger.error(traceback.print_exc())
        return 0
    if not data:
        return 0
    logger.debug(f"data: {data}")
    minCost  = min(data, key=(lambda site: site.get('rate', 0)), default=0)
    minCost = minCost.get('rate', 0) + minCost.get('tax', 0)
    return int(minCost)


def get_price(hotel_key, start, end):
    """start: datetime
    end: datetime"""
    assert start < end
    result = []
    while start < end:
        result.append(cost(hotel_key, start))
        start += timedelta(days=1)
        logger.debug((end - start).days)
    return result

if __name__ == "__main__":
    print(cost("g187221-d584620", date(2026, 1, 22)))