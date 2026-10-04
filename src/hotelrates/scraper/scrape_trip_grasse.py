"""
Scrape les hôtels autour de Grasse sur Trip.com pour une date donnée.

Ce script utilise requests + BeautifulSoup sur la page de résultats Trip.com,
qui expose déjà dans le HTML initial les premières cartes hôtel, avec leurs
prix visibles.

Usage:
    python scrape_trip_grasse.py --checkin 2026-07-31
    python scrape_trip_grasse.py --checkin 2026-07-31 --checkout 2026-08-02 --limit 10
    python scrape_trip_grasse.py --checkin 2026-07-31 --output trip_grasse.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup, Tag

TRIP_SEARCH_URL = "https://fr.trip.com/hotels/list"

SEARCH_PARAMS = {
    "flexType": "1",
    "fixedDate": "0",
    "cityId": "23038",
    "provinceId": "10216",
    "districtId": "0",
    "countryId": "31",
    "cityName": "Grasse",
    "destName": "Grasse, Alpes-Maritimes, Provence-Alpes-Côte d'Azur, France",
    "searchWord": "Grasse",
    "searchType": "CT",
    "optionId": "23038",
    "searchValue": "19|23038*19*23038",
    "curr": "EUR",
    "locale": "fr-FR",
    "old": "1",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}


@dataclass
class HotelPrice:
    name: str
    area: str
    price_eur: float
    taxes_fees_eur: float | None
    total_eur: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape les prix Trip.com des hôtels proches de Grasse pour une date donnée."
    )
    parser.add_argument("--checkin", required=True, help="Date d'arrivée au format YYYY-MM-DD.")
    parser.add_argument(
        "--checkout",
        help="Date de départ au format YYYY-MM-DD. Par défaut: le lendemain du checkin.",
    )
    parser.add_argument("--adults", type=int, default=2, help="Nombre d'adultes (défaut: 2).")
    parser.add_argument("--rooms", type=int, default=1, help="Nombre de chambres (défaut: 1).")
    parser.add_argument("--limit", type=int, default=10, help="Nombre max d'hôtels (défaut: 10).")
    parser.add_argument("--output", help="Fichier CSV de sortie.")
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_params(checkin: date, checkout: date, adults: int, rooms: int) -> dict[str, str]:
    params = dict(SEARCH_PARAMS)
    params.update(
        {
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "crn": str(rooms),
            "adult": str(adults),
        }
    )
    return params


def parse_euro_amounts(text: str) -> list[float]:
    amounts = []
    for match in re.findall(r"(\d[\d\s.,]*)\s*€", text.replace("\xa0", " ")):
        normalized = match.replace(" ", "").replace(",", ".")
        try:
            amounts.append(float(normalized))
        except ValueError:
            continue
    return amounts


def parse_area(text: str) -> str:
    match = re.search(r"À proximité de\s+(.+?)\s+Afficher sur la carte", text)
    if match:
        return match.group(1).strip()
    return ""


def parse_price_block(text: str) -> tuple[float | None, float | None, float | None]:
    amounts = parse_euro_amounts(text)
    if not amounts:
        return None, None, None
    if len(amounts) == 1:
        return amounts[0], None, amounts[0]

    taxes_match = re.search(r"\+\s*(\d[\d\s.,]*)\s*€\s*taxes et frais", text)
    taxes = None
    if taxes_match:
        taxes_list = parse_euro_amounts(taxes_match.group(0))
        taxes = taxes_list[0] if taxes_list else None

    price = amounts[-2] if taxes is not None and len(amounts) >= 2 else amounts[-1]
    total = price + taxes if taxes is not None else price
    return price, taxes, total


def extract_hotels_from_html(html: str, limit: int) -> list[HotelPrice]:
    hotels: list[HotelPrice] = []

    pattern = re.compile(
        r'class="hotel-info".*?class="hotelName">(?P<name>[^<]+)</span>'
        r'(?P<info>.*?)class="room-right">(?P<room_right>.*?)</div></div></div></div>',
        re.S,
    )

    for match in pattern.finditer(html):
        name = match.group("name").strip()
        info_text = BeautifulSoup(match.group("info"), "html.parser").get_text(" ", strip=True)
        room_text = BeautifulSoup(match.group("room_right"), "html.parser").get_text(" ", strip=True)

        price, taxes, total = parse_price_block(room_text)
        if price is None:
            continue

        hotels.append(
            HotelPrice(
                name=name,
                area=parse_area(info_text),
                price_eur=price,
                taxes_fees_eur=taxes,
                total_eur=total,
            )
        )

        if len(hotels) >= limit:
            break

    return hotels


def extract_hotels_from_soup(soup: BeautifulSoup, limit: int) -> list[HotelPrice]:
    hotels: list[HotelPrice] = []

    for info in soup.select("div.hotel-info"):
        if not isinstance(info, Tag):
            continue
        name_tag = info.select_one("span.hotelName")
        if name_tag is None:
            continue

        card_text = info.get_text(" ", strip=True)
        room_right = info.parent.select_one("div.room-right") if info.parent else None
        if room_right is None:
            continue

        price_text = room_right.get_text(" ", strip=True)
        price, taxes, total = parse_price_block(price_text)
        if price is None:
            continue

        hotels.append(
            HotelPrice(
                name=name_tag.get_text(" ", strip=True),
                area=parse_area(card_text),
                price_eur=price,
                taxes_fees_eur=taxes,
                total_eur=total,
            )
        )

        if len(hotels) >= limit:
            break

    return hotels


def scrape_trip_grasse(
    checkin: date,
    checkout: date,
    adults: int = 2,
    rooms: int = 1,
    limit: int = 10,
    timeout: float = 20,
) -> list[HotelPrice]:
    response = requests.get(
        TRIP_SEARCH_URL,
        params=build_params(checkin, checkout, adults, rooms),
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    hotels = extract_hotels_from_soup(soup, limit)
    if hotels:
        return hotels
    return extract_hotels_from_html(response.text, limit)


def write_csv(path: str, hotels: list[HotelPrice]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["hotel", "zone", "prix_eur", "taxes_frais_eur", "total_eur"])
        for hotel in hotels:
            writer.writerow(
                [
                    hotel.name,
                    hotel.area,
                    hotel.price_eur,
                    hotel.taxes_fees_eur if hotel.taxes_fees_eur is not None else "",
                    hotel.total_eur if hotel.total_eur is not None else "",
                ]
            )


def main() -> None:
    args = parse_args()

    try:
        checkin = parse_iso_date(args.checkin)
        checkout = parse_iso_date(args.checkout) if args.checkout else checkin + timedelta(days=1)
    except ValueError:
        print("Les dates doivent être au format YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    if checkout <= checkin:
        print("La date de départ doit être strictement postérieure à la date d'arrivée.", file=sys.stderr)
        sys.exit(1)

    try:
        hotels = scrape_trip_grasse(
            checkin=checkin,
            checkout=checkout,
            adults=args.adults,
            rooms=args.rooms,
            limit=args.limit,
        )
    except requests.RequestException as exc:
        print(f"Erreur réseau: {exc}", file=sys.stderr)
        sys.exit(1)

    if not hotels:
        print("Aucun hôtel avec prix trouvé.")
        return

    if args.output:
        write_csv(args.output, hotels)
        print(f"{len(hotels)} hôtels enregistrés dans {args.output}")
        return

    print(json.dumps([hotel.__dict__ for hotel in hotels], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()