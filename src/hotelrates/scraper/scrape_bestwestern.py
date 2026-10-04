"""
Scraper de prix pour l'Hôtel Elixir Grasse (Best Western Plus Hôtel Elixir Grasse).

Le site vitrine (hotelelixirgrasse.com) redirige son moteur de réservation vers
le moteur D-EDGE : https://www.secure-hotel-booking.com/d-edge/BW-Plus-Hotel-Elixir/JSF7/...

Ce moteur accepte directement les dates de séjour en paramètres d'URL
(arrivalDate / departureDate), ce qui permet d'aller chercher, pour chaque nuit
souhaitée, le prix le moins cher toutes chambres confondues affiché sur la page
"Sélectionner une chambre" (attribut data-testid="bestRate-price").

Le site est protégé par DataDome (anti-bot). On utilise donc un vrai navigateur
piloté par Playwright (et pas de simples requêtes HTTP) pour se comporter comme
un visiteur normal, avec un délai aléatoire entre deux requêtes.

⚠️ AVERTISSEMENT IMPORTANT (constaté en testant ce script) :
Le moteur de réservation (secure-hotel-booking.com) est protégé par DataDome,
une solution anti-bot avancée. Lors des tests de mise au point de ce script,
quelques requêtes automatisées rapprochées ont suffi à faire bloquer
temporairement notre adresse IP (page "An error has occurred" / HTTP 403),
et ce quel que soit le navigateur utilisé (Chromium classique, Chromium
"stealth", ou même un navigateur piloté manuellement). Cela signifie que :
  - Ce script peut se faire bloquer après seulement quelques dates scrapées,
    même avec des délais de plusieurs secondes.
  - Un blocage se traduit par une page de challenge/erreur au lieu du prix :
    le script traitera alors ces dates comme "indisponible" à tort.
  - Après un blocage, il faut généralement attendre (souvent plusieurs
    minutes à quelques heures) avant que l'IP ne soit débloquée.
  - Vérifie les conditions d'utilisation du site et du moteur D-EDGE avant
    toute utilisation répétée ou à grande échelle : ce type de protection
    est justement conçu pour empêcher ce genre de scraping automatisé.

Recommandations pratiques :
  - Commence par tester sur une toute petite plage de dates (2-3 jours).
  - Utilise des délais longs (--min-delay/--max-delay, 10-20s ou plus).
  - Ne lance pas le script en boucle/planifié sans t'assurer que c'est
    autorisé par le site.

Installation :
    pip install -r requirements.txt
    playwright install chromium

Utilisation :
    python scrape_hotel_prices.py 2026-08-01 2026-08-10
    python scrape_hotel_prices.py 2026-08-01 2026-08-10 --output aout.csv --headless
"""

import argparse
import csv
import random
import sys
import time
from datetime import date, datetime, timedelta

from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

BASE_URL = (
    "https://www.secure-hotel-booking.com/d-edge/BW-Plus-Hotel-Elixir/JSF7/"
    "15231/fr-FR/RoomSelection"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

PRICE_SELECTOR = '[data-testid="bestRate-price"]'
NO_AVAILABILITY_SELECTOR = '[data-testid="no-availability-modify-search"]'


def parse_price(text: str) -> float | None:
    """Convertit un texte de prix ("113 €", "1 234,56 €") en float."""
    cleaned = text.replace("\xa0", " ").replace("€", "").strip()
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def scrape_price_for_date(page: Page, checkin: date, checkout: date) -> float | None:
    """Retourne le prix le moins cher (toutes chambres) pour un séjour checkin -> checkout,
    ou None si aucune disponibilité."""
    url = f"{BASE_URL}?arrivalDate={checkin.isoformat()}&departureDate={checkout.isoformat()}"
    page.goto(url, wait_until="domcontentloaded")

    try:
        page.wait_for_selector(
            f"{PRICE_SELECTOR}, {NO_AVAILABILITY_SELECTOR}",
            timeout=20000,
        )
    except PlaywrightTimeoutError:
        print(
            f"  -> Timeout en attendant les résultats pour {checkin.isoformat()}",
            file=sys.stderr,
        )
        return None

    if page.query_selector(NO_AVAILABILITY_SELECTOR):
        return None

    prices = []
    for el in page.query_selector_all(PRICE_SELECTOR):
        price = parse_price(el.inner_text())
        if price is not None:
            prices.append(price)

    return min(prices) if prices else None


def daterange(start: date, end: date):
    """Génère chaque date de start (inclus) à end (exclu)."""
    current = start
    while current < end:
        yield current
        current += timedelta(days=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape le prix le moins cher d'une chambre à l'Hôtel Elixir Grasse "
            "pour chaque nuit entre deux dates."
        )
    )
    parser.add_argument("start_date", help="Date de début, format YYYY-MM-DD (incluse)")
    parser.add_argument("end_date", help="Date de fin, format YYYY-MM-DD (exclue)")
    parser.add_argument(
        "--output", default="prices.csv", help="Fichier CSV de sortie (défaut: prices.csv)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Lance le navigateur en mode headless (par défaut: navigateur visible)",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=8.0,
        help="Délai minimum entre deux requêtes, en secondes (défaut: 8s, "
        "à augmenter si le site bloque, cf. avertissement DataDome ci-dessus)",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=15.0,
        help="Délai maximum entre deux requêtes, en secondes (défaut: 15s)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    except ValueError:
        print("Les dates doivent être au format YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    if start >= end:
        print("La date de début doit être strictement antérieure à la date de fin.", file=sys.stderr)
        sys.exit(1)

    results: list[tuple[str, float | None]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(user_agent=USER_AGENT, locale="fr-FR")
        page = context.new_page()

        try:
            for checkin in daterange(start, end):
                checkout = checkin + timedelta(days=1)
                price = scrape_price_for_date(page, checkin, checkout)
                results.append((checkin.isoformat(), price))
                label = f"{price} €" if price is not None else "indisponible"
                print(f"{checkin.isoformat()} -> {label}")
                time.sleep(random.uniform(args.min_delay, args.max_delay))
        finally:
            browser.close()

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "prix_eur"])
        for d, price in results:
            writer.writerow([d, price if price is not None else ""])

    print(f"\nRésultats enregistrés dans {args.output}")


if __name__ == "__main__":
    main()
