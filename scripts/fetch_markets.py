# -*- coding: utf-8 -*-
"""Tägliche Marktdaten (Aktienindizes, Gold, Silber, Bitcoin).

Zwei Quellen statt einer: Yahoo-Chart-API und Stooq-CSV (pokedata/sources/
markets.py). Die alte Fassung hing allein an der inoffiziellen Yahoo-API mit
`range=1mo` – nach einem Ausfall von mehr als einem Monat entstand eine
unwiederbringliche Lücke. Jetzt wird der Abfragezeitraum aus dem letzten
gespeicherten Datum abgeleitet und bei Ausfall die zweite Quelle genutzt.

Gold/Silber kommen bevorzugt als Spot-Reihen (Stooq XAUUSD/XAGUSD); Front-
Futures erzeugen Roll-Sprünge in Renditereihen.

Die Rohschlusskurse werden je Symbol gesammelt (data/markets_raw.csv.gz); die
Anzeige-Niveaus entstehen in build_indices.py durch Renditen-Verkettung an die
importierte Historie 2013-2026.

Aufruf:  python scripts/fetch_markets.py
"""
from __future__ import annotations

import csv
import gzip
import os
import sys

from common import DATA_DIR

from pokedata.atomicio import write_gzip_csv
from pokedata.sources import markets as msrc

MARKETS_RAW = os.path.join(DATA_DIR, "markets_raw.csv.gz")
MARKETS_HIST = os.path.join(DATA_DIR, "markets_hist.csv")
KEEP_DAYS = 400        # Rest steckt in markets_hist.csv


def read_raw() -> dict:
    rows = {}
    if os.path.isfile(MARKETS_RAW):
        with gzip.open(MARKETS_RAW, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    rows[(r["series"], r["date"])] = float(r["close"])
                except (TypeError, ValueError):
                    continue
    return rows


def hist_last_dates() -> dict:
    """Letztes Datum je Reihe in der importierten Historie."""
    out = {}
    if not os.path.isfile(MARKETS_HIST):
        return out
    with open(MARKETS_HIST, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        names = [c for c in (rd.fieldnames or []) if c != "Date"]
        for r in rd:
            for n in names:
                if r.get(n):
                    out[n] = r["Date"]
    return out


def main() -> int:
    rows = read_raw()
    hist_end = hist_last_dates()
    added = 0
    failures = []
    for series in msrc.SYMBOLS:
        have = [d for (s, d) in rows if s == series]
        last = max(have) if have else hist_end.get(series)
        try:
            data, src = msrc.fetch_series(series, last)
        except Exception as exc:                          # noqa: BLE001
            failures.append(f"{series}: {exc}")
            print(f"  {series}: FEHLER {exc} – nächster Lauf holt nach")
            continue
        new = 0
        for d, c in data.items():
            if (series, d) not in rows:
                rows[(series, d)] = c
                new += 1
        added += new
        print(f"  {series}: {new} neue Kurse (Quelle {src}, "
              f"letzter {max(data) if data else '-'})")

    by_series = {}
    for (series, d), c in rows.items():
        by_series.setdefault(series, []).append((d, c))
    trimmed = {}
    for series, lst in by_series.items():
        for d, c in sorted(lst)[-KEEP_DAYS:]:
            trimmed[(series, d)] = c

    write_gzip_csv(MARKETS_RAW, ["series", "date", "close"],
                   [[s, d, f"{trimmed[(s, d)]:.6f}"] for (s, d) in sorted(trimmed)])
    print(f"Märkte: {added} neue Schlusskurse gespeichert.")
    if len(failures) == len(msrc.SYMBOLS):
        print("FEHLER: keine einzige Reihe konnte aktualisiert werden.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
