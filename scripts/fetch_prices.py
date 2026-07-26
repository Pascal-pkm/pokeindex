# -*- coding: utf-8 -*-
"""Täglicher Preisabzug von tcgcsv.com (TCGplayer Market Prices, Pokémon).

Regeln
------
* Preis je Produkt = Market Price des wertvollsten regulären Printings
  (1st Edition ausgeschlossen, highPrice nie verwendet).
* Printing-Stabilität: existiert für das Printing des Vortags ein Marktpreis,
  wird es beibehalten. Ohne diese Regel entstehen Scheinrenditen, sobald das
  teuerste Printing wechselt (Holo <-> Reverse Holo).
* Einzelkarten mit Hysterese: Neuaufnahme ab 25 USD, Beibehaltung bis 15 USD.
  Vorher fielen Karten beim Unterschreiten von 25 USD aus den Daten – die
  Zensur entfernte genau die Verlierer und verzerrte Ranking und Basket.
* Sealed: alle Produkte, unabhängig vom Preis.
* Datum = offizieller tcgcsv-Stand (last-updated.txt), nicht die lokale Uhr.
* Der Tag wird nur geschrieben, wenn er die Validierung besteht (Zeilenzahl,
  Plausibilität, Duplikate) – ein abgebrochener Abzug darf die Historie nicht
  überschreiben.

Aufruf:  python scripts/fetch_prices.py [--force]
"""
from __future__ import annotations

import argparse
import sys

from common import (
    KEEP_STORE_PRICE,
    MIN_STORE_PRICE,
    choose_price,
    classify_product,
    read_last_daily,
    read_products,
    write_daily,
    write_products,
)

from pokedata import quality
from pokedata.sources.tcgcsv import TcgCsv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="auch bei Validierungsfehlern schreiben")
    args = ap.parse_args()

    api = TcgCsv()
    datum = api.official_date()
    print(f"tcgcsv-Datenstand: {datum}")

    products = read_products()
    prev_sub = read_last_daily()
    known_cards = {pid for pid, p in products.items() if p["is_sealed"] == 0}

    groups = api.groups()
    if not groups:
        print("FEHLER: keine Gruppen erhalten – Abbruch (Tag wird nicht geschrieben)")
        return 1

    rows = []
    kept_by_hysteresis = 0
    for i, g in enumerate(groups, 1):
        gid, gname = g["groupId"], g["name"]
        prods = api.products(gid)
        prices = api.prices(gid)
        if not prods or not prices:
            continue
        by_product = {}
        for p in prices:
            by_product.setdefault(p["productId"], []).append(p)
        for prod in prods:
            pid = prod["productId"]
            is_sealed, cat, number, rarity = classify_product(
                prod.get("name"), prod.get("extendedData"))
            if is_sealed == -1:
                continue
            best = choose_price(by_product.get(pid, []), prev_sub.get(pid))
            if best is None:
                continue
            price, sub = best
            if is_sealed == 0:
                limit = KEEP_STORE_PRICE if pid in known_cards else MIN_STORE_PRICE
                if price < limit:
                    continue
                if price < MIN_STORE_PRICE:
                    kept_by_hysteresis += 1
            rows.append((pid, round(price * 100), sub))
            products[pid] = {
                "product_id": pid, "name": prod.get("name"),
                "clean_name": prod.get("cleanName"), "group_id": gid,
                "group_name": gname, "number": number, "rarity": rarity,
                "is_sealed": is_sealed, "sealed_cat": cat,
                "url": prod.get("url")}
        if i % 25 == 0:
            print(f"  {i}/{len(groups)} Gruppen, {len(rows)} Preise")

    # ---- Validierung vor dem Schreiben ----
    rep = quality.Report()
    quality.check_prices(rows, rep, label=f"Abzug {datum}")
    from common import have_dates, read_daily
    counts = {}
    for d in have_dates()[-10:]:
        try:
            counts[d] = len(read_daily(d))
        except OSError:
            continue
    counts[datum] = len(rows)
    quality.check_rowcount(counts, rep, label="Tagesdatei")
    print("Validierung:")
    print(rep.render())
    if rep.failed and not args.force:
        print("Abbruch: Tag wird NICHT geschrieben (--force überschreibt).")
        return 1

    write_daily(datum, rows)
    write_products(products)
    print(f"Fertig: {len(rows)} Preise für {datum} gespeichert "
          f"({kept_by_hysteresis} Karten nur dank Hysterese erhalten).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
