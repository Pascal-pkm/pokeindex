# -*- coding: utf-8 -*-
"""
Täglicher CS2-Preisabzug über die öffentliche Skinport-API (ohne Login).

  GET https://api.skinport.com/v1/items?app_id=730&currency=USD
  (Antwort ist Brotli-komprimiert -> Paket 'brotli' nötig; Cache 5 Min.)

Preisdefinition: median_price der aktuellen Angebote (Fallback min_price).
Gespeichert werden ALLE Items (für EW-Index), inkl. Menge (Liquidität) und
created_at (Seasoning-Filter wie in der Masterarbeit).

Dateien:
  data/cs2_items.csv.gz          item_id <-> market_hash_name, URL, created_at
  data/cs2_daily/JJJJ-MM-TT.csv.gz   item_id,cents,quantity

Aufruf:  python scripts/fetch_cs2.py
"""
import csv
import datetime as dt
import gzip
import io
import os
import sys

import requests

from common import ROOT, USER_AGENT

CS2_ITEMS = os.path.join(ROOT, "data", "cs2_items.csv.gz")
CS2_DAILY = os.path.join(ROOT, "data", "cs2_daily")
API = "https://api.skinport.com/v1/items?app_id=730&currency=USD"


def read_items():
    if not os.path.isfile(CS2_ITEMS):
        return {}, 0
    out, mx = {}, 0
    with gzip.open(CS2_ITEMS, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            iid = int(row["item_id"])
            out[row["name"]] = {"item_id": iid, "name": row["name"],
                                "url": row["url"], "created": row["created"]}
            mx = max(mx, iid)
    return out, mx


def write_items(items):
    os.makedirs(os.path.dirname(CS2_ITEMS), exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["item_id", "name", "url", "created"])
    w.writeheader()
    for it in sorted(items.values(), key=lambda x: x["item_id"]):
        w.writerow(it)
    with gzip.open(CS2_ITEMS, "wt", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def main():
    r = requests.get(API, headers={"User-Agent": USER_AGENT,
                                   "Accept-Encoding": "br, gzip"}, timeout=120)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        print("Unerwartete Skinport-Antwort")
        return 1

    items, next_id = read_items()
    datum = dt.datetime.utcnow().date().isoformat()
    rows = []
    for it in data:
        name = it.get("market_hash_name")
        price = it.get("median_price") or it.get("min_price")
        if not name or price is None:
            continue
        rec = items.get(name)
        if rec is None:
            next_id += 1
            rec = {"item_id": next_id, "name": name,
                   "url": it.get("item_page") or "",
                   "created": str(it.get("created_at") or "")}
            items[name] = rec
        rows.append((rec["item_id"], round(price * 100), it.get("quantity") or 0))

    os.makedirs(CS2_DAILY, exist_ok=True)
    with gzip.open(os.path.join(CS2_DAILY, f"{datum}.csv.gz"), "wt",
                   encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "cents", "quantity"])
        for row in sorted(rows):
            w.writerow(row)
    write_items(items)
    print(f"CS2: {len(rows)} Item-Preise für {datum} gespeichert "
          f"({len(items)} Items bekannt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
