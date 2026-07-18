# -*- coding: utf-8 -*-
"""
Täglicher Preisabzug von tcgcsv.com (TCGplayer Market Prices, Kategorie Pokemon).

- Lädt alle Gruppen (Sets), deren Produkte und Tagespreise
- Karten: wertvollstes reguläres Printing (ohne 1st Edition), Speicherung ab 25 USD
- Sealed: alle Produkte
- Datum = offizieller tcgcsv-Stand (last-updated.txt), nicht die lokale Uhr

Aufruf:  python scripts/fetch_prices.py
"""
import sys
import time

import requests

from common import (BASE_URL, CATEGORY, MIN_STORE_PRICE, USER_AGENT,
                    choose_price, classify_product, read_products,
                    write_daily, write_products)

S = requests.Session()
S.headers.update({"User-Agent": USER_AGENT})


def get_json(url, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def official_date():
    r = S.get("https://tcgcsv.com/last-updated.txt", timeout=30)
    r.raise_for_status()
    return r.text.strip()[:10]


def main():
    datum = official_date()
    print(f"tcgcsv-Datenstand: {datum}")
    products = read_products()
    groups = get_json(f"{BASE_URL}/{CATEGORY}/groups")["results"]
    rows = []
    for i, g in enumerate(groups, 1):
        gid, gname = g["groupId"], g["name"]
        prods = get_json(f"{BASE_URL}/{CATEGORY}/{gid}/products")
        prices = get_json(f"{BASE_URL}/{CATEGORY}/{gid}/prices")
        if not prods or not prices:
            continue
        by_product = {}
        for p in prices.get("results", []):
            by_product.setdefault(p["productId"], []).append(p)
        for prod in prods.get("results", []):
            pid = prod["productId"]
            is_sealed, cat, number, rarity = classify_product(
                prod.get("name"), prod.get("extendedData"))
            if is_sealed == -1:
                continue
            best = choose_price(by_product.get(pid, []))
            if best is None:
                continue
            price, sub = best
            if is_sealed == 0 and price < MIN_STORE_PRICE:
                continue
            rows.append((pid, round(price * 100), sub))
            products[pid] = {
                "product_id": pid, "name": prod.get("name"),
                "clean_name": prod.get("cleanName"), "group_id": gid,
                "group_name": gname, "number": number, "rarity": rarity,
                "is_sealed": is_sealed, "sealed_cat": cat,
                "url": prod.get("url")}
        if i % 25 == 0:
            print(f"  {i}/{len(groups)} Gruppen, {len(rows)} Preise")
        time.sleep(0.25)
    write_daily(datum, rows)
    write_products(products)
    print(f"Fertig: {len(rows)} Preise für {datum} gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
