# -*- coding: utf-8 -*-
"""
Tägliche Marktdaten (Aktien-Indizes, Gold, Silber, Bitcoin) über die
öffentliche Yahoo-Finance-Chart-API (ohne API-Key).

Die Rohschlusskurse werden je Symbol gesammelt (data/markets_raw.csv.gz).
Die Anzeige-Niveaus entstehen später in build_indices.py durch
Renditen-Verkettung an die importierte Historie 2013-2026 – dadurch sind
Quellen-/Niveauunterschiede (z. B. MSCI World via URTH-ETF) unschädlich.

Aufruf:  python scripts/fetch_markets.py
"""
import csv
import gzip
import io
import os
import sys
import time

import requests

from common import ROOT, USER_AGENT

MARKETS_RAW = os.path.join(ROOT, "data", "markets_raw.csv.gz")
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d"

# Reihenname (wie in der Historie-CSV) -> Yahoo-Symbol
SYMBOLS = {
    "SP500": "^GSPC",
    "DAX": "^GDAXI",
    "NASDAQ100": "^NDX",
    "EUROSTOXX50": "^STOXX50E",
    "MSCIWORLD": "URTH",       # iShares-MSCI-World-ETF als Renditeproxy
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "BITCOIN": "BTC-USD",
}


def read_raw():
    rows = {}
    if os.path.isfile(MARKETS_RAW):
        with gzip.open(MARKETS_RAW, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows[(r["series"], r["date"])] = float(r["close"])
    return rows


def write_raw(rows):
    os.makedirs(os.path.dirname(MARKETS_RAW), exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["series", "date", "close"])
    for (series, date) in sorted(rows):
        w.writerow([series, date, f"{rows[(series, date)]:.6f}"])
    with gzip.open(MARKETS_RAW, "wt", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def main():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    rows = read_raw()
    added = 0
    for series, sym in SYMBOLS.items():
        try:
            r = s.get(YAHOO.format(sym=sym.replace("^", "%5E")), timeout=60)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            ts = res.get("timestamp") or []
            closes = ((res.get("indicators") or {}).get("adjclose")
                      or [{}])[0].get("adjclose") or \
                     ((res.get("indicators") or {}).get("quote")
                      or [{}])[0].get("close") or []
            for t, c in zip(ts, closes):
                if c is None:
                    continue
                d = time.strftime("%Y-%m-%d", time.gmtime(t))
                if (series, d) not in rows:
                    rows[(series, d)] = float(c)
                    added += 1
        except Exception as e:
            print(f"  {series} ({sym}): FEHLER {e} – nächster Lauf holt nach")
        time.sleep(1)
    # Nur die letzten ~400 Tage je Reihe behalten (Rest steckt in der Historie)
    by_series = {}
    for (series, d), c in rows.items():
        by_series.setdefault(series, []).append((d, c))
    trimmed = {}
    for series, lst in by_series.items():
        for d, c in sorted(lst)[-400:]:
            trimmed[(series, d)] = c
    write_raw(trimmed)
    print(f"Märkte: {added} neue Schlusskurse gespeichert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
