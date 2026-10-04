"""
Scraper de prix pour l'Hôtel CasaBella (Mouans-Sartoux).

Le site vitrine (https://www.hotel-casabella.com/) redirige vers le moteur de
réservation Octorate (https://book.octorate.com/...) pour la disponibilité et
les prix. Cette page est intégralement générée côté serveur (JSF), donc les prix
des chambres sont présents directement dans le HTML, sans appel AJAX/JS
supplémentaire à imiter : une simple requête HTTP + parsing HTML suffit (pas
besoin de piloter un vrai navigateur).

Usage en ligne de commande:
    python scrape_casabella.py --checkin 2026-08-15
    python scrape_casabella.py --checkin 2026-08-15 --checkout 2026-08-17 --adults 2

Usage en tant que module (veille_competitive, hotels.yml direct: scrape_casabella.py):
    from hotelrates.scraper.scrape_casabella import cost
    price = cost("2026-08-15")  # int EUR, 0 si indisponible ou erreur
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Union

import requests
from bs4 import BeautifulSoup

# Identifiant de l'hôtel CasaBella sur le moteur de réservation Octorate.
HOTEL_CODE = "33793"
BASE_URL = "https://book.octorate.com/octobook/site/reservation/result.xhtml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

DateLike = Union[str, date, datetime]


@dataclass
class RoomOffer:
    """Une offre de chambre disponible pour les dates demandées."""

    name: str
    price: float
    currency: str = "EUR"


def _to_date_str(value: DateLike) -> str:
    """Normalise une date (str 'YYYY-MM-DD', date ou datetime) vers 'YYYY-MM-DD'."""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    # Valide le format et normalise au passage.
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return parsed.strftime("%Y-%m-%d")


def _parse_price(price_div) -> float:
    """Convertit un bloc HTML de prix (ex: '€138' + '<sup>,00</sup>') en float."""
    text = price_div.get_text(" ", strip=True).replace("€", "")
    integer_part, _, decimal_part = text.partition(",")
    integer_part = re.sub(r"\D", "", integer_part)
    decimal_part = re.sub(r"\D", "", decimal_part) or "00"
    if not integer_part:
        raise ValueError(f"Impossible d'extraire un prix depuis: {text!r}")
    return float(f"{integer_part}.{decimal_part}")


def _fetch_offers(
    checkin: DateLike,
    checkout: DateLike | None = None,
    adults: int = 2,
    hotel_code: str = HOTEL_CODE,
    timeout: float = 15,
) -> list[RoomOffer]:
    """Récupère la liste des chambres disponibles (nom + prix) pour les dates données."""
    checkin_str = _to_date_str(checkin)
    if checkout is None:
        checkout_str = (
            datetime.strptime(checkin_str, "%Y-%m-%d").date() + timedelta(days=1)
        ).strftime("%Y-%m-%d")
    else:
        checkout_str = _to_date_str(checkout)

    params = {
        "codice": hotel_code,
        "checkin": checkin_str,
        "checkout": checkout_str,
        "pax": adults,
        "lang": "fr",
    }

    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    offers: list[RoomOffer] = []
    for room_section in soup.find_all("section", class_="room"):
        name_tag = room_section.find("h1")
        price_div = room_section.find("div", class_="price")
        if name_tag is None or price_div is None:
            continue
        try:
            price = _parse_price(price_div)
        except ValueError:
            continue
        offers.append(RoomOffer(name=name_tag.get_text(strip=True), price=price))

    return offers


def get_room_price(
    checkin: DateLike,
    checkout: DateLike | None = None,
    adults: int = 2,
) -> Union[float, bool]:
    """
    Retourne le prix minimum (en EUR) d'une chambre disponible pour la période
    donnée, ou False si aucune chambre n'est disponible.

    checkin: date d'arrivée ('YYYY-MM-DD', date ou datetime).
    checkout: date de départ (par défaut: le lendemain de checkin).
    adults: nombre d'adultes (défaut 2).
    """
    offers = _fetch_offers(checkin, checkout, adults)
    if not offers:
        return False
    return min(offer.price for offer in offers)


def cost(night: DateLike, adults: int = 2) -> int:
    """Prix minimum d'une nuit, même contrat que xotelo.cost (0 = pas de prix).

    Appelé par veille_competitive quand hotels.yml contient
    direct: scrape_casabella.py pour cet hôtel.
    """
    try:
        price = get_room_price(night, adults=adults)
    except Exception:
        return 0
    if not price:
        return 0
    return int(price)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Récupère le prix d'une chambre à l'hôtel CasaBella pour une date donnée."
    )
    parser.add_argument("--checkin", required=True, help="Date d'arrivée (YYYY-MM-DD)")
    parser.add_argument(
        "--checkout", help="Date de départ (YYYY-MM-DD). Par défaut: checkin + 1 jour."
    )
    parser.add_argument("--adults", type=int, default=2, help="Nombre d'adultes (défaut: 2)")
    args = parser.parse_args()

    try:
        offers = _fetch_offers(args.checkin, args.checkout, args.adults)
    except requests.RequestException as exc:
        print(f"Erreur réseau: {exc}", file=sys.stderr)
        sys.exit(1)

    if not offers:
        print(False)
        return

    cheapest = min(offers, key=lambda o: o.price)
    print(f"{cheapest.price} {cheapest.currency} ({cheapest.name})")


if __name__ == "__main__":
    main()
