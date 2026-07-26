# -*- coding: utf-8 -*-
"""Backfill der Preishistorie aus dem tcgcsv-Archiv (verfügbar ab 2024-02-08).

Lädt pro Aufruf bis zu --days fehlende Archivtage (neueste zuerst), extrahiert
nur die Pokémon-Kategorie und speichert die Tagespreise nach denselben Regeln
wie fetch_prices.py (Printing-Stabilität gegen den chronologisch nächsten
vorhandenen Tag, Hysterese bei Einzelkarten).

Bereits vorhandene Tage werden übersprungen; das Skript ist idempotent und
beliebig oft wiederholbar. Ein 404 des Archivs wird als "Tag existiert nicht"
markiert (leere Datei), damit er nicht in jedem Lauf erneut versucht wird.

Aufruf:  python scripts/backfill_archive.py --days 30
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

import requests
from common import (
    ARCHIVE_START,
    ARCHIVE_URL,
    CATEGORY,
    KEEP_STORE_PRICE,
    MIN_STORE_PRICE,
    USER_AGENT,
    choose_price,
    have_dates,
    read_daily,
    read_products,
    write_daily,
)

S = requests.Session()
S.headers.update({"User-Agent": USER_AGENT})


def missing_dates(limit: int) -> list:
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


def reference_subtypes(datum: str) -> dict:
    """Printing-Referenz: der nächstgelegene bereits vorhandene Tag.

    Beim Rückwärts-Backfill ist der chronologisch NÄCHSTE vorhandene Tag die
    passende Referenz; so bleibt die Printing-Auswahl über die Naht hinweg
    konsistent.
    """
    dates = have_dates()
    if not dates:
        return {}
    later = [d for d in dates if d > datum]
    earlier = [d for d in dates if d < datum]
    ref = later[0] if later else (earlier[-1] if earlier else None)
    if not ref:
        return {}
    try:
        return {pid: sub for pid, _c, sub in read_daily(ref)}
    except OSError:
        return {}


def _py7zr():
    """py7zr erst beim tatsächlichen Entpacken laden.

    py7zr braucht pyppmd; für sehr neue Python-Versionen (z. B. 3.14) gibt es
    davon noch kein Wheel, sodass pip einen C-Compiler verlangt. Der Import
    stand vorher am Dateianfang und ließ damit die gesamte lokale Installation
    scheitern – obwohl der Backfill in GitHub Actions läuft und lokal nur
    selten gebraucht wird.
    """
    try:
        import py7zr
        return py7zr
    except ImportError as exc:
        raise SystemExit(
            "py7zr ist nicht installiert – der Archiv-Backfill braucht es zum "
            "Entpacken.\n"
            "  Variante 1 (empfohlen): den Backfill in GitHub Actions laufen "
            "lassen (Actions -> 'Historie-Backfill' -> Run workflow).\n"
            "  Variante 2: pip install -r requirements-optional.txt\n"
            "              (braucht auf Python 3.13+ die Microsoft C++ Build "
            "Tools, weil noch kein Wheel existiert)\n"
            f"  Ursprüngliche Meldung: {exc}") from exc


def ingest_day(datum: str, tmpdir: str, products: dict):
    py7zr = _py7zr()
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

    prev_sub = reference_subtypes(datum)
    known_cards = {pid for pid, p in products.items() if p["is_sealed"] == 0}
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
                best = choose_price(plist, prev_sub.get(pid))
                if best is None:
                    continue
                price, sub = best
                if prod["is_sealed"] == 0:
                    limit = KEEP_STORE_PRICE if pid in known_cards else MIN_STORE_PRICE
                    if price < limit:
                        continue
                rows.append((pid, round(price * 100), sub))
    os.remove(arc)
    shutil.rmtree(os.path.join(tmpdir, datum), ignore_errors=True)
    return rows


def main() -> int:
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
    failed = 0
    try:
        for datum in todo:
            try:
                rows = ingest_day(datum, tmpdir, products)
                if rows is None:
                    write_daily(datum, [])
                    continue
                if not rows:
                    print(f"    {datum}: 0 Preise – wird NICHT geschrieben "
                          f"(nächster Lauf versucht es erneut)")
                    failed += 1
                    continue
                write_daily(datum, rows)
                print(f"    {datum}: {len(rows)} Preise")
            except Exception as exc:                       # noqa: BLE001
                failed += 1
                print(f"    {datum}: FEHLER {exc} – nächster Lauf versucht es erneut")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if failed:
        print(f"{failed} Tage offen geblieben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
