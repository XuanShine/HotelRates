"""
Scrape les hotels proches de Grasse sur Google Hotels (Google Travel).

Le script ouvre la recherche Google Hotels, accepte le bandeau de consentement
si present, puis extrait les cartes hotel visibles avec leur prix en euros.

Usage:
    python scrape_google_hotels_grasse.py
    python scrape_google_hotels_grasse.py --query "Grasse" --limit 20
    python scrape_google_hotels_grasse.py --output google_hotels_grasse.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

GOOGLE_HOTELS_SEARCH_URL = "https://www.google.com/travel/search"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


@dataclass
class HotelPrice:
    name: str
    price_eur: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape les prix Google Hotels pour les hotels proches de Grasse."
    )
    parser.add_argument(
        "--query",
        default="Grasse",
        help="Lieu recherche (defaut: Grasse).",
    )
    parser.add_argument(
        "--checkin",
        help="Date d'arrivee au format YYYY-MM-DD.",
    )
    parser.add_argument(
        "--checkout",
        help="Date de depart au format YYYY-MM-DD. Par defaut: le lendemain du checkin.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Nombre maximum d'hotels a retourner (defaut: 20).",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=8,
        help="Nombre max de scrolls pour charger plus de resultats (defaut: 8).",
    )
    parser.add_argument(
        "--output",
        help="Fichier CSV de sortie. Si absent, affiche le JSON dans la console.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Lance Chromium en mode headless.",
    )
    return parser.parse_args()


def build_search_url(query: str) -> str:
    return f"{GOOGLE_HOTELS_SEARCH_URL}?q={quote_plus(query)}&hl=fr&gl=FR"


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_price_to_float(text: str) -> float | None:
    matches = re.findall(r"(\d[\d\s.,]*)\s*€", text.replace("\xa0", " "))
    if not matches:
        return None
    value = matches[-1].replace(" ", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def accept_google_consent_if_present(page: Page) -> None:
    candidates = [
        page.get_by_role("button", name="Tout accepter"),
        page.get_by_role("button", name="I agree"),
    ]
    for button in candidates:
        try:
            if button.count() and button.first.is_visible(timeout=1200):
                button.first.click(timeout=5000)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2500)
                return
        except Exception:
            continue


def _date_to_google_aria_label(value: date) -> str:
    weekdays = [
        "lundi",
        "mardi",
        "mercredi",
        "jeudi",
        "vendredi",
        "samedi",
        "dimanche",
    ]
    months = [
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ]
    weekday = weekdays[value.weekday()]
    month = months[value.month - 1]
    return f"{weekday} {value.day} {month} {value.year}"


def apply_dates(page: Page, checkin: date, checkout: date) -> None:
    arrival_box = page.get_by_role("textbox", name="Arrivée")
    if not arrival_box.count():
        arrival_box = page.get_by_role("textbox", name="Arrivee")
    if not arrival_box.count():
        arrival_box = page.locator('input[aria-label*="Arriv" i], textarea[aria-label*="Arriv" i]')

    arrival_box.first.click(timeout=8000)
    page.wait_for_timeout(700)

    checkin_label = _date_to_google_aria_label(checkin)
    checkout_label = _date_to_google_aria_label(checkout)

    checkin_cell = page.locator(f'[aria-label^="{checkin_label}"]').first
    checkout_cell = page.locator(f'[aria-label^="{checkout_label}"]').first

    checkin_cell.wait_for(timeout=12000)
    checkin_cell.click(timeout=5000)
    checkout_cell.wait_for(timeout=12000)
    checkout_cell.click(timeout=5000)

    ok_button = page.get_by_role("button", name="OK")
    try:
        if ok_button.count() and ok_button.first.is_visible(timeout=800):
            ok_button.first.click(timeout=3000)
    except Exception:
        pass

    page.wait_for_timeout(2200)


def extract_hotels(page: Page) -> list[HotelPrice]:
    raw_cards = page.evaluate(
        r"""
        () => {
          const normalize = (t) => (t || '').replace(/\s+/g, ' ').trim();
          const cards = Array.from(document.querySelectorAll('div.jVsyI'));
          const rows = [];

          for (const card of cards) {
            const name = normalize(card.querySelector('h2')?.textContent);
            if (!name) continue;

            const text = normalize(card.textContent);
            const prices = [...text.matchAll(/(\d[\d\s.,]*)\s*€/g)].map((m) => m[0]);
            if (!prices.length) continue;

            rows.push({ name, priceText: prices[0] });
          }

          return rows;
        }
        """
    )

    by_name: dict[str, HotelPrice] = {}
    for item in raw_cards:
        price = parse_price_to_float(item["priceText"])
        if price is None:
            continue

        name = item["name"].strip()
        existing = by_name.get(name)
        if existing is None or price < existing.price_eur:
            by_name[name] = HotelPrice(name=name, price_eur=price)

    return sorted(by_name.values(), key=lambda h: h.price_eur)


def load_results(page: Page, limit: int, max_scrolls: int) -> list[HotelPrice]:
    previous_count = -1
    stable_rounds = 0

    for _ in range(max_scrolls + 1):
        hotels = extract_hotels(page)
        current_count = len(hotels)
        if current_count >= limit:
            return hotels[:limit]

        if current_count == previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            previous_count = current_count

        if stable_rounds >= 2:
            return hotels[:limit]

        page.evaluate("window.scrollBy(0, window.innerHeight * 1.8)")
        page.wait_for_timeout(1400)

    return extract_hotels(page)[:limit]


def scrape_google_hotels(
    query: str = "Grasse",
    checkin: date | None = None,
    checkout: date | None = None,
    limit: int = 20,
    max_scrolls: int = 8,
    headless: bool = False,
) -> list[HotelPrice]:
    url = build_search_url(query)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=DEFAULT_USER_AGENT, locale="fr-FR")
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=50000)
            accept_google_consent_if_present(page)

            if checkin is not None and checkout is not None:
                apply_dates(page, checkin, checkout)

            try:
                page.wait_for_selector("h2", timeout=20000)
            except PlaywrightTimeoutError as exc:
                body = page.locator("body").inner_text(timeout=8000)
                if re.search(r"captcha|robot|unusual|traffic|forbidden|access denied", body, re.I):
                    raise RuntimeError("Google a probablement declenche une protection anti-bot.") from exc
                raise RuntimeError("Les resultats Google Hotels ne se sont pas charges a temps.") from exc

            page.wait_for_timeout(2200)
            return load_results(page, limit=limit, max_scrolls=max_scrolls)
        finally:
            context.close()
            browser.close()


def write_csv(path: str, hotels: list[HotelPrice]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["hotel", "prix_eur"])
        for hotel in hotels:
            writer.writerow([hotel.name, hotel.price_eur])


def main() -> None:
    args = parse_args()

    if args.limit <= 0:
        print("--limit doit etre > 0.", file=sys.stderr)
        sys.exit(1)
    if args.max_scrolls < 0:
        print("--max-scrolls doit etre >= 0.", file=sys.stderr)
        sys.exit(1)

    checkin: date | None = None
    checkout: date | None = None
    if args.checkin:
        try:
            checkin = parse_iso_date(args.checkin)
            checkout = parse_iso_date(args.checkout) if args.checkout else checkin + timedelta(days=1)
        except ValueError:
            print("Les dates doivent etre au format YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

        if checkout <= checkin:
            print("La date de depart doit etre strictement posterieure a la date d'arrivee.", file=sys.stderr)
            sys.exit(1)

    try:
        hotels = scrape_google_hotels(
            query=args.query,
            checkin=checkin,
            checkout=checkout,
            limit=args.limit,
            max_scrolls=args.max_scrolls,
            headless=args.headless,
        )
    except Exception as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        sys.exit(1)

    if not hotels:
        print("Aucun hotel avec prix trouve.")
        return

    if args.output:
        write_csv(args.output, hotels)
        print(f"{len(hotels)} hotels enregistres dans {args.output}")
        return

    print(json.dumps([hotel.__dict__ for hotel in hotels], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
