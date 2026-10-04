"""
Scrape les prix des hotels proches de Grasse sur KAYAK avec Playwright.

Usage:
    python scrape_kayak_grasse.py --checkin 2026-07-31
    python scrape_kayak_grasse.py --checkin 2026-07-31 --checkout 2026-08-02 --limit 20
    python scrape_kayak_grasse.py --checkin 2026-07-31 --output kayak_grasse.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

KAYAK_BASE_URL = "https://www.kayak.fr/hotels/Grasse,France-c43800"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


@dataclass
class HotelPrice:
    name: str
    min_price_eur: float
    provider: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape les prix KAYAK des hotels proches de Grasse pour une date donnee."
    )
    parser.add_argument("--checkin", required=True, help="Date d'arrivee au format YYYY-MM-DD.")
    parser.add_argument(
        "--checkout",
        help="Date de depart au format YYYY-MM-DD. Par defaut: le lendemain du checkin.",
    )
    parser.add_argument("--adults", type=int, default=2, help="Nombre d'adultes (defaut: 2).")
    parser.add_argument("--limit", type=int, default=20, help="Nombre max d'hotels (defaut: 20).")
    parser.add_argument("--output", help="Fichier CSV de sortie.")
    parser.add_argument("--headless", action="store_true", help="Lance Chromium en mode headless.")
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_search_url(checkin: date, checkout: date, adults: int) -> str:
    return (
        f"{KAYAK_BASE_URL}/{checkin.isoformat()}/{checkout.isoformat()}/"
        f"{adults}adults;map?sort=rank_a"
    )


def _dismiss_overlays(page: Page) -> None:
    selectors = [
        'button:has-text("Accepter")',
        'button:has-text("J\'accepte")',
        'button:has-text("Tout accepter")',
        'button:has-text("Fermer")',
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=800):
                button.click(timeout=1000)
                page.wait_for_timeout(300)
        except Exception:
            continue


def _load_results(page: Page) -> None:
    _dismiss_overlays(page)

    for _ in range(12):
        has_offers = page.evaluate(
            """
            () => document.querySelectorAll('a[href*="/book/hotel?"]').length > 5
            """
        )
        if has_offers:
            break
        page.wait_for_timeout(1000)

    last_count = -1
    stable_rounds = 0
    for _ in range(8):
        offer_count = page.evaluate(
            """
            () => document.querySelectorAll('a[href*="/book/hotel?"]').length
            """
        )

        if offer_count == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_count = offer_count

        if stable_rounds >= 2:
            break

        page.evaluate("window.scrollBy(0, window.innerHeight * 1.8)")
        page.wait_for_timeout(1200)


def extract_hotels(page: Page, limit: int) -> list[HotelPrice]:
    raw = page.evaluate(
        r"""
        () => {
          const normalize = (text) => (text || '').replace(/\s+/g, ' ').trim();

                    const cards = Array.from(document.querySelectorAll('div[class*="S0Ps-resultInner"]'));
                    const rows = [];

                    for (const card of cards) {
                        const name = normalize(
                            card.querySelector('a[class*="c9Hnq-big-name"], div[class*="c9Hnq-hotel-name"]')?.textContent
                        );
                        if (!name) continue;

                        const offerLinks = Array.from(card.querySelectorAll('a[href*="/book/hotel?"]'));
                        if (!offerLinks.length) continue;

                        let minPrice = null;
                        for (const link of offerLinks) {
                            const text = normalize(link.textContent);
                            const prices = [...text.matchAll(/(\d[\d\s.,]*)\s*€/g)].map((m) => m[1]);
                            if (!prices.length) continue;

                            const candidate = Number.parseFloat(prices[prices.length - 1].replace(/\s+/g, '').replace(',', '.'));
                            if (!Number.isFinite(candidate)) continue;
                            if (minPrice === null || candidate < minPrice) minPrice = candidate;
                        }

                        if (minPrice === null) continue;
                        rows.push({ name, min_price_eur: minPrice, provider: 'KAYAK' });
                    }

                    // Fallback si la classe de carte change: agrege a partir des liens d'offres.
                    if (!rows.length) {
                        const grouped = new Map();
                        const links = Array.from(document.querySelectorAll('a[href*="/book/hotel?"]'));

                        for (const link of links) {
                            const text = normalize(link.textContent);
                            const prices = [...text.matchAll(/(\d[\d\s.,]*)\s*€/g)].map((m) => m[1]);
                            if (!prices.length) continue;
                            const price = Number.parseFloat(prices[prices.length - 1].replace(/\s+/g, '').replace(',', '.'));
                            if (!Number.isFinite(price)) continue;

                            let rank = '';
                            try {
                                rank = new URL(link.getAttribute('href') || '', window.location.origin).searchParams.get('viewRank') || '';
                            } catch {
                                rank = '';
                            }

                            const key = rank || `offer-${Math.round(price)}`;
                            const current = grouped.get(key);
                            if (!current || price < current.min_price_eur) {
                                grouped.set(key, { name: `Hotel ${key}`, min_price_eur: price, provider: 'KAYAK' });
                            }
                        }
                        rows.push(...Array.from(grouped.values()));
                    }

          rows.sort((a, b) => a.min_price_eur - b.min_price_eur);
          return rows;
        }
        """
    )

    hotels: list[HotelPrice] = []
    for item in raw:
        name = (item.get("name") or "").strip()
        if not name:
            continue

        hotels.append(
            HotelPrice(
                name=name,
                min_price_eur=float(item["min_price_eur"]),
                provider=(item.get("provider") or "").strip(),
            )
        )
        if len(hotels) >= limit:
            break

    return hotels


def scrape_kayak_grasse(
    checkin: date,
    checkout: date,
    adults: int = 2,
    limit: int = 20,
    headless: bool = False,
) -> list[HotelPrice]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=DEFAULT_USER_AGENT, locale="fr-FR")
        page = context.new_page()

        try:
            url = build_search_url(checkin, checkout, adults)
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            _dismiss_overlays(page)

            try:
                page.wait_for_selector('main, [aria-label*="Résultats"]', timeout=30000)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError("La page KAYAK n'a pas charge a temps.") from exc

            _load_results(page)
            hotels = extract_hotels(page, limit)

            if not hotels:
                body = page.locator("body").inner_text(timeout=5000)
                if re.search(r"captcha|robot|challenge|forbidden|access denied", body, re.I):
                    raise RuntimeError("KAYAK a probablement declenche une protection anti-bot.")

            return hotels
        finally:
            context.close()
            browser.close()


def write_csv(path: str, hotels: list[HotelPrice]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["hotel", "prix_min_eur", "fournisseur"])
        for hotel in hotels:
            writer.writerow([hotel.name, hotel.min_price_eur, hotel.provider])


def main() -> None:
    args = parse_args()

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
        hotels = scrape_kayak_grasse(
            checkin=checkin,
            checkout=checkout,
            adults=args.adults,
            limit=args.limit,
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
