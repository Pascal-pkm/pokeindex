# -*- coding: utf-8 -*-
"""
Backfill der Preishistorie aus dem tcgcsv-Archiv (verfügbar ab 2024-02-08).

Lädt pro Aufruf bis zu --days fehlende Archivtage (neueste zuerst), extrahiert
nur die Pokemon-Kategorie und speichert die Tagespreise wie fetch_prices.py.
Bereits vorhandene Tage (= Datei in data/daily/) werden übersprungen; das
Skript kann beliebig oft laufen, bis die Historie vollständig ist.

Wichtig: Es werden nur Preise für Produkte übernommen, die in
data/products.csv.gz bekannt sind (einmal fetch_prices.py vorher laufen lassen).

Aufruf:  python scripts/backfill_archive.py --days 30
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

import py7zr
import requests

from common import (ARCHIVE_START, ARCHIVE_URL, CATEGORY, MIN_STORE_PRICE,
                    USER_AGENT, choose_price, have_dates, read_products,
                    write_daily)

S = requests.Session()
S.headers.update({"User-Agent": USER_AGENT})


def missing_dates(limit):
    done = set(have_dates())
    start = dt.date.fromisoformat(ARCHIVE_START)
    end = dt.date.today() - dt.timedelta(days=1)
    out, d = [], end
    while d >= start and len(out) < limit:
        s = d.isoformat()
        if s not in done:
            out.append(s)
        d -= dt.timedelta(days=1)
    return out


def ingest_day(datum, tmpdir, products):
    url = ARCHIVE_URL.format(d=datum)
    r = S.get(url, timeout=900, stream=True)
    if r.status_code == 404:
        print(f"    {datum}: kein Archiv vorhanden, übersprungen")
        return None
    r.raise_for_status()
    arc = os.path.join(tmpdir, f"{datum}.7z")
    with open(arc, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)

    with py7zr.SevenZipFile(arc, mode="r") as z:
        names = [n for n in z.getnames()
                 if f"/{CATEGORY}/" in n and n.endswith("prices")]
        z.extract(path=tmpdir, targets=names)

    rows = []
    catdir = os.path.join(tmpdir, datum, str(CATEGORY))
    if os.path.isdir(catdir):
        for group_id in os.listdir(catdir):
            pf = os.path.join(catdir, group_id, "prices")
            if not os.path.isfile(pf):
                continue
            with open(pf, encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    continue
            by_product = {}
            for p in data.get("results", []):
                by_product.setdefault(p["productId"], []).append(p)
            for pid, plist in by_product.items():
                prod = products.get(pid)
                if prod is None:
                    continue
                best = choose_price(plist)
                if best is None:
                    continue
                price, sub = best
                if prod["is_sealed"] == 0 and price < MIN_STORE_PRICE:
                    continue
                rows.append((pid, round(price * 100), sub))
    os.remove(arc)
    shutil.rmtree(os.path.join(tmpdir, datum), ignore_errors=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    products = read_products()
    if not products:
        print("Keine Produktliste – bitte zuerst fetch_prices.py ausführen.")
        return 1
    todo = missing_dates(args.days)
    if not todo:
        print("Backfill komplett – nichts zu tun.")
        return 0
    print(f"{len(todo)} Archivtage zu laden ...")
    tmpdir = tempfile.mkdtemp(prefix="tcgcsv_")
    try:
        for datum in todo:
            try:
                rows = ingest_day(datum, tmpdir, products)
                if rows is None:          # 404: als leeren Tag markieren
                    write_daily(datum, [])
                    continue
                write_daily(datum, rows)
                print(f"    {datum}: {len(rows)} Preise")
            except Exception as e:
                print(f"    {datum}: FEHLER {e} – nächster Lauf versucht es erneut")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
