# -*- coding: utf-8 -*-
"""Täglicher CS2-Preisabzug über die öffentliche Skinport-API (ohne Login).

Preisdefinition und ihre Grenze: `median_price` ist der Median der AKTUELLEN
ANGEBOTE (Ask), kein Verkaufspreis. Er liegt strukturell über dem
realisierbaren Preis. Die Steam-Vorgeschichte des Index besteht dagegen aus
tatsächlichen Verkäufen – der Quellenbruch wird beim Verketten ausdrücklich
markiert (siehe build_indices.py, Feld `splice`).

Datum = Serverzeit der Antwort (HTTP-Date), nicht die lokale Uhr des Runners.

Dateien:
  data/cs2_items.csv.gz              item_id <-> market_hash_name, URL, created_at
  data/cs2_daily/JJJJ-MM-TT.csv.gz   item_id,cents,quantity

Aufruf:  python scripts/fetch_cs2.py
"""
from __future__ import annotations

import csv
import gzip
import os
import sys

from common import DATA_DIR

from pokedata import quality
from pokedata.atomicio import write_gzip_csv, write_gzip_dictcsv
from pokedata.sources import skinport

CS2_ITEMS = os.path.join(DATA_DIR, "cs2_items.csv.gz")
CS2_DAILY = os.path.join(DATA_DIR, "cs2_daily")
ITEM_FIELDS = ["item_id", "name", "url", "created"]


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


def main() -> int:
    data, datum = skinport.fetch_items()
    normalized = skinport.normalize(data)
    if not normalized:
        print("FEHLER: keine verwertbaren Items in der Skinport-Antwort")
        return 1

    items, next_id = read_items()
    rows = []
    for name, cents, qty, created in normalized:
        rec = items.get(name)
        if rec is None:
            next_id += 1
            rec = {"item_id": next_id, "name": name, "url": "",
                   "created": created}
            items[name] = rec
        elif created and not rec.get("created"):
            rec["created"] = created
        rows.append((rec["item_id"], cents, qty))

    rep = quality.Report()
    quality.check_prices([(a, b, "") for a, b, _q in rows], rep, label=f"CS2 {datum}")
    existing = sorted(f[:-7] for f in os.listdir(CS2_DAILY)) \
        if os.path.isdir(CS2_DAILY) else []
    counts = {}
    for d in existing[-10:]:
        try:
            with gzip.open(os.path.join(CS2_DAILY, f"{d}.csv.gz"), "rt") as f:
                counts[d] = sum(1 for _ in f) - 1
        except OSError:
            continue
    counts[datum] = len(rows)
    quality.check_rowcount(counts, rep, label="CS2-Tagesdatei")
    print("Validierung:")
    print(rep.render())
    if rep.failed:
        print("Abbruch: CS2-Tag wird NICHT geschrieben.")
        return 1

    write_gzip_csv(os.path.join(CS2_DAILY, f"{datum}.csv.gz"),
                   ["item_id", "cents", "quantity"], sorted(rows))
    write_gzip_dictcsv(CS2_ITEMS, ITEM_FIELDS,
                       sorted(items.values(), key=lambda x: x["item_id"]))
    print(f"CS2: {len(rows)} Item-Preise für {datum} gespeichert "
          f"({len(items)} Items bekannt, Preisart '{skinport.PRICE_KIND}').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
