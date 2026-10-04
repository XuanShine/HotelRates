"""
Scrape les hôtels autour de Grasse sur Agoda pour une date donnée.

Le script ouvre directement la page de recherche Agoda pour Grasse via une URL
minimale (city=10550), puis extrait les cartes hôtel rendues dans le DOM.

Usage:
    python scrape_agoda_grasse.py --checkin 2026-07-31
    python scrape_agoda_grasse.py --checkin 2026-07-31 --checkout 2026-08-02 --limit 20
    python scrape_agoda_grasse.py --checkin 2026-07-31 --output agoda_grasse.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

import requests
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

AGODA_SEARCH_URL = "https://www.agoda.com/fr-fr/search"
AGODA_SUGGEST_URL = (
    "https://www.agoda.com/api/cronos/search/GetUnifiedSuggestResult/3/1/1/0/fr-fr/"
)
GRASSE_CITY_ID = 10550
FRANCE_COUNTRY_ID = 153
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


# Colonnes du sheet qui ne sont pas des hôtels concurrents.
NON_HOTEL_COLUMNS = {
    "evenement",
    "maj",
    "dispo",
    "libre",
    "aroma",
    "ecart_to",
    "ecart to",
}

# short du sheet -> (jetons requis dans le nom/zone, requête Agoda si absent de la liste Grasse)
SHEET_HOTELS = {
    "LaPoste": (["poste"], "Hotel de la Poste Grasse"),
    "Casabella": (["casabella"], "Hotel Casabella Mouans-Sartoux"),
    "BestWestern": (["elixir"], "Best Western Elixir Grasse"),
    "BnBMouans": (["mouans", "b"], "B&B Hotel Mouans-Sartoux"),
    "IbisCannes": (["ibis", "budget", "cannes"], "Ibis Budget Cannes Centre"),
    "IbisMouans": (["ibis", "mouans"], "Ibis Mouans-Sartoux"),
    "Bellaudiere": (["bellaudi"], "Hotel Bellaudiere Grasse"),
    "EspritDAzur": (["esprit", "azur"], "Esprit d Azur Grasse"),
}


@dataclass
class HotelPrice:
    name: str
    area: str
    price_eur: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape les prix Agoda des hôtels proches de Grasse pour une date donnée."
    )
    parser.add_argument(
        "--checkin",
        help="Date d'arrivée au format YYYY-MM-DD.",
    )
    parser.add_argument(
        "--checkout",
        help="Date de départ au format YYYY-MM-DD. Par défaut: le lendemain du checkin.",
    )
    parser.add_argument(
        "--adults",
        type=int,
        default=2,
        help="Nombre d'adultes (défaut: 2).",
    )
    parser.add_argument(
        "--rooms",
        type=int,
        default=1,
        help="Nombre de chambres (défaut: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Nombre maximum d'hôtels à retourner (défaut: 30).",
    )
    parser.add_argument(
        "--output",
        help="Fichier CSV de sortie. Si absent, affiche les résultats dans la console.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Lance Chromium en mode headless.",
    )
    parser.add_argument(
        "--update-sheet",
        action="store_true",
        help="Met à jour Feuille1 (hôtels hors Aroma) pour les N prochains jours.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Nombre de jours à écrire avec --update-sheet (défaut: 10).",
    )
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_search_url(
    checkin: date,
    checkout: date,
    adults: int,
    rooms: int,
    query: str | None = None,
) -> str:
    url = (
        f"{AGODA_SEARCH_URL}?checkIn={checkin.isoformat()}"
        f"&checkOut={checkout.isoformat()}"
        f"&rooms={rooms}"
        f"&adults={adults}"
        "&children=0"
        "&priceCur=EUR"
        f"&los={(checkout - checkin).days}"
        "&locale=fr-fr"
        "&currency=EUR"
    )
    if query:
        return f"{url}&textToSearch={quote_plus(query)}"
    return f"{url}&city={GRASSE_CITY_ID}"


def build_property_url(
    hotel_id: int,
    city_id: int,
    checkin: date,
    checkout: date,
    adults: int,
    rooms: int,
) -> str:
    return (
        f"{AGODA_SEARCH_URL}?hotel={hotel_id}&selectedproperty={hotel_id}&city={city_id}"
        f"&checkIn={checkin.isoformat()}"
        f"&checkOut={checkout.isoformat()}"
        f"&rooms={rooms}"
        f"&adults={adults}"
        "&children=0"
        "&priceCur=EUR"
        f"&los={(checkout - checkin).days}"
        "&locale=fr-fr"
        "&currency=EUR"
    )


@dataclass
class AgodaProperty:
    hotel_id: int
    city_id: int
    name: str
    city: str


def suggest_properties(query: str) -> list[AgodaProperty]:
    """Hôtels Agoda proposés pour un nom. L'ordre est celui de la suggestion."""
    response = requests.get(
        AGODA_SUGGEST_URL,
        params={"searchText": query},
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    properties = []
    for item in response.json().get("ViewModelList", []):
        if not item.get("IsHotel") or item.get("CountryId") != FRANCE_COUNTRY_ID:
            continue
        hotel_id = item.get("ObjectId")
        city_id = item.get("CityId")
        if not hotel_id or not city_id:
            continue
        properties.append(
            AgodaProperty(
                hotel_id=int(hotel_id),
                city_id=int(city_id),
                name=item.get("Name") or "",
                city=item.get("CityName") or "",
            )
        )
    return properties


_PROPERTY_CACHE: dict[str, AgodaProperty | None] = {}


def resolve_property(short: str) -> AgodaProperty | None:
    """Premier hôtel Agoda dont le nom correspond à la colonne du sheet."""
    if short in _PROPERTY_CACHE:
        return _PROPERTY_CACHE[short]
    query = SHEET_HOTELS.get(short, (None, short))[1]
    properties = suggest_properties(query)
    cards = [
        HotelPrice(name=prop.name, area=prop.city, price_eur=float(index))
        for index, prop in enumerate(properties)
    ]
    matched = match_sheet_hotels(cards, [short])
    chosen = None
    if short in matched:
        for prop in properties:
            if prop.name == matched[short].name and prop.city == matched[short].area:
                chosen = prop
                break
    _PROPERTY_CACHE[short] = chosen
    return chosen


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    folded = folded.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def match_sheet_hotels(cards: list[HotelPrice], shorts: list[str]) -> dict[str, HotelPrice]:
    """Associe les cartes Agoda aux colonnes du sheet. Un hôtel = une carte."""
    found: dict[str, HotelPrice] = {}
    for short in shorts:
        spec = SHEET_HOTELS.get(short)
        tokens = spec[0] if spec else _norm(short).split()
        hits = []
        for card in cards:
            blob = _norm(f"{card.name} {card.area}")
            if short == "BnBMouans":
                ok = "mouans" in blob and ("b and b" in blob or "bnb" in blob)
            elif short == "IbisMouans":
                ok = "ibis" in blob and "mouans" in blob and "budget" not in blob
            elif short == "IbisCannes":
                ok = (
                    "ibis" in blob
                    and "budget" in blob
                    and "cannes" in blob
                    and "centre" in blob
                    and "mougins" not in blob
                    and "mouans" not in blob
                )
            elif short == "LaPoste":
                ok = (
                    "poste" in blob
                    and "grasse" in blob
                    and "piscine" not in blob
                    and "peymeinade" not in blob
                )
            elif short == "EspritDAzur":
                ok = "esprit" in blob and "azur" in blob and any(
                    city in blob for city in ("grasse", "mouans", "mougins", "peymeinade", "magagnosc")
                )
            else:
                ok = all(token in blob for token in tokens)
            if ok:
                hits.append(card)
        if hits:
            found[short] = min(hits, key=lambda card: card.price_eur)
    return found


def parse_price_to_float(text: str) -> float | None:
    cleaned = text.replace("\xa0", " ")
    matches = re.findall(r"(\d[\d\s.,]*)\s*€", cleaned)
    if not matches:
        matches = re.findall(r"€\s*(\d[\d\s.,]*)", cleaned)
    if not matches:
        return None
    numeric = matches[-1].replace(" ", "").replace(",", ".")
    try:
        return float(numeric)
    except ValueError:
        return None


def extract_cards(page: Page) -> list[HotelPrice]:
    raw_cards = page.evaluate(
        r"""
        () => Array.from(document.querySelectorAll('[data-selenium="hotel-item"]')).map((card) => {
            const name = card.querySelector('[data-selenium="hotel-name"]')?.textContent?.trim() || '';
            const area = card.querySelector('[data-selenium="area-city-text"]')?.textContent?.replace(/\s+/g, ' ').trim() || '';
            const priceBlock = card.querySelector('[data-element-name="property-card-price"]');
            const priceText = priceBlock ? priceBlock.textContent.replace(/\s+/g, ' ').trim() : '';
            return { name, area, priceText };
        })
        """
    )

    hotels: list[HotelPrice] = []
    for item in raw_cards:
        if not item["name"]:
            continue
        price = parse_price_to_float(item["priceText"])
        if price is None:
            continue
        hotels.append(
            HotelPrice(
                name=item["name"],
                area=item["area"],
                price_eur=price,
            )
        )
    return hotels


def load_all_results(page: Page, limit: int) -> list[HotelPrice]:
    previous_count = -1
    stable_rounds = 0

    for round_index in range(12):
        page.evaluate(
            """
            () => {
              const card = document.querySelector('[data-selenium="hotel-item"]');
              let el = document.scrollingElement || document.documentElement;
              let node = card ? card.parentElement : null;
              while (node) {
                if (node.scrollHeight > node.clientHeight + 40) {
                  el = node;
                  break;
                }
                node = node.parentElement;
              }
              el.scrollTop = Math.min(el.scrollTop + el.clientHeight, el.scrollHeight);
            }
            """
        )
        page.wait_for_timeout(1200)
        item_count = page.locator('[data-selenium="hotel-item"]').count()
        if item_count >= limit or (item_count == previous_count and round_index >= 4):
            stable_rounds += 1
        else:
            stable_rounds = 0
            previous_count = item_count
        if stable_rounds >= 2:
            break

    return extract_cards(page)[:limit]


def _dismiss_consent(page: Page) -> None:
    for name in ("Accepter", "Tout accepter", "J'accepte", "Accept"):
        try:
            button = page.get_by_role("button", name=name).first
            if button.is_visible(timeout=800):
                button.click(timeout=2000)
                page.wait_for_timeout(400)
                return
        except Exception:
            continue


def _open_results(
    page: Page,
    checkin: date,
    checkout: date,
    adults: int,
    rooms: int,
    limit: int,
    query: str | None = None,
    property_id: tuple[int, int] | None = None,
) -> list[HotelPrice]:
    if property_id:
        hotel_id, city_id = property_id
        url = build_property_url(hotel_id, city_id, checkin, checkout, adults, rooms)
    else:
        url = build_search_url(checkin, checkout, adults, rooms, query=query)
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    _dismiss_consent(page)
    try:
        page.wait_for_selector('[data-selenium="hotel-item"]', timeout=20000)
    except PlaywrightTimeoutError as exc:
        body_text = page.locator("body").inner_text(timeout=5000)
        if re.search(r"captcha|robot|verify|challenge|forbidden", body_text, re.I):
            raise RuntimeError("Agoda a probablement déclenché une protection anti-bot.") from exc
        return []
    page.wait_for_timeout(1500)
    return load_all_results(page, limit)


def scrape_sheet_hotels(
    checkin: date,
    shorts: list[str],
    checkout: date | None = None,
    adults: int = 2,
    rooms: int = 1,
    headless: bool = True,
) -> dict[str, HotelPrice]:
    """Prix Agoda des colonnes demandées pour une nuit. Liste Grasse, puis recherche ciblée."""
    if checkout is None:
        checkout = checkin + timedelta(days=1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="fr-FR",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        try:
            return _prices_on_page(page, checkin, checkout, shorts, adults, rooms)
        finally:
            context.close()
            browser.close()


def _prices_on_page(page, checkin, checkout, shorts, adults, rooms) -> dict[str, HotelPrice]:
    cards = _open_results(page, checkin, checkout, adults, rooms, limit=50)
    found = match_sheet_hotels(cards, shorts)
    for short in shorts:
        if short in found or short not in SHEET_HOTELS:
            continue
        prop = resolve_property(short)
        if prop is None:
            continue
        targeted = _open_results(
            page,
            checkin,
            checkout,
            adults,
            rooms,
            limit=20,
            property_id=(prop.hotel_id, prop.city_id),
        )
        found.update(match_sheet_hotels(targeted, [short]))
        time.sleep(1.2)
    return found


def update_sheet_prices(days: int = 10, sheet_key: str | None = None, headless: bool = True) -> None:
    """Écrit les prix Agoda des hôtels du sheet (sauf Aroma) pour les `days` prochains jours."""
    import os

    import gspread
    import yaml

    from hotelrates.adapters import sheets as ss
    from hotelrates.paths import REPO_ROOT

    if sheet_key is None:
        with open(os.path.join(REPO_ROOT, "clients.yml"), "r") as handle:
            sheet_key = yaml.safe_load(handle)["Aroma"]["key"]

    worksheet = ss.client.open_by_key(sheet_key).worksheet("Feuille1")
    headers = worksheet.row_values(1)
    date_labels = worksheet.col_values(1)
    shorts = []
    columns = {}
    for index, header in enumerate(headers, start=1):
        if _norm(header) in NON_HOTEL_COLUMNS or not header.strip():
            continue
        shorts.append(header)
        columns[header] = index

    start = date.today()
    nights = [start + timedelta(days=offset) for offset in range(days)]
    cells = []
    missing = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="fr-FR",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        try:
            for night in nights:
                label = night.strftime("%d/%m/%Y")
                try:
                    row = date_labels.index(label) + 1
                except ValueError:
                    missing.append(f"{label}: ligne absente")
                    continue
                try:
                    found = _prices_on_page(page, night, night + timedelta(days=1), shorts, 2, 1)
                except RuntimeError as exc:
                    print(f"{label} arrêté: {exc}", file=sys.stderr)
                    break
                for short, hotel in found.items():
                    price = int(hotel.price_eur)
                    if price <= 0:
                        continue
                    cells.append(gspread.Cell(row=row, col=columns[short], value=price))
                    print(f"{label} {short} {price} ({hotel.name})", flush=True)
                if cells:
                    worksheet.update_cells(cells, value_input_option="USER_ENTERED")
                    print(f"{len(cells)} cellules écrites.", flush=True)
                    cells = []
                absent = [short for short in shorts if short not in found]
                if absent:
                    missing.append(f"{label}: {', '.join(absent)}")
                time.sleep(2)
        finally:
            context.close()
            browser.close()

    if missing:
        print("Sans prix: " + " | ".join(missing))


def scrape_agoda_grasse(
    checkin: date,
    checkout: date,
    adults: int = 2,
    rooms: int = 1,
    limit: int = 30,
    headless: bool = False,
) -> list[HotelPrice]:
    url = build_search_url(checkin, checkout, adults, rooms)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="fr-FR",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector('[data-selenium="hotel-item"]', timeout=20000)
            except PlaywrightTimeoutError as exc:
                body_text = page.locator("body").inner_text(timeout=5000)
                if re.search(r"captcha|robot|verify|challenge|forbidden", body_text, re.I):
                    raise RuntimeError("Agoda a probablement déclenché une protection anti-bot.") from exc
                raise RuntimeError("Les résultats Agoda n'ont pas chargé à temps.") from exc

            page.wait_for_timeout(2500)
            return load_all_results(page, limit)
        finally:
            context.close()
            browser.close()


def write_csv(path: str, hotels: list[HotelPrice]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["hotel", "zone", "prix_eur"])
        for hotel in hotels:
            writer.writerow([hotel.name, hotel.area, hotel.price_eur])


def main() -> None:
    args = parse_args()

    if args.update_sheet:
        if args.days <= 0:
            print("--days doit être > 0.", file=sys.stderr)
            sys.exit(1)
        try:
            update_sheet_prices(days=args.days, headless=True)
        except Exception as exc:
            print(f"Erreur: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if not args.checkin:
        print("--checkin est requis sans --update-sheet.", file=sys.stderr)
        sys.exit(1)

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
        hotels = scrape_agoda_grasse(
            checkin=checkin,
            checkout=checkout,
            adults=args.adults,
            rooms=args.rooms,
            limit=args.limit,
            headless=args.headless,
        )
    except Exception as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
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