# -*- coding: utf-8 -*-
"""
Einmaliger Export der bereits gescrapten PriceCharting-Bestände
(karten.sqlite3, sealed.sqlite3) in kompakte JS/JSON-Dateien für die Website
("Alle Karten"- und "Alle Sealed"-Ansicht mit monatlicher Historie).

Grades (PriceCharting-Konvention für Karten):
  used       -> Ungraded (Raw)
  graded     -> Grade 9
  manualonly -> PSA 10

Ausgabe:
  site/data/pc_cards.js            Suchliste aller Karten (id, Name, Set, letzter Preis)
  site/data/pc/cards_<s>.js        Historien-Shards (id % 64)
  site/data/pc_sealed.js           Suchliste aller Sealed-Produkte
  site/data/pc/sealed_<s>.js       Historien-Shards (id % 8)

Aufruf:
  python scripts/export_pricecharting.py --karten "../karten.sqlite3" --sealed "../sealed.sqlite3"
"""
import argparse
import json
import os
import sqlite3
import sys

from common import ROOT, SITE_DATA

CARD_SHARDS = 64
SEALED_SHARDS = 8
CARD_GRADES = {"used": "u", "graded": "g9", "manualonly": "p10"}
SEALED_GRADES = {"used": "u", "new": "n", "graded": "g"}


def titel(slug_or_name):
    if not slug_or_name:
        return ""
    return slug_or_name.replace("-", " ").title()


def export(db_path, table, price_table, id_col, grades, shards, list_var,
           shard_prefix, shard_var, extra_cols=""):
    con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    items = {r["id"]: dict(r) for r in con.execute(
        f"SELECT id, url, set_slug, name{extra_cols} FROM {table}")}
    print(f"  {len(items)} Einträge aus {os.path.basename(db_path)}")

    series = {}    # id -> {gradekey: [[JJJJ-MM, cents], ...]}
    latest = {}    # id -> letzter used-Preis (cents)
    q = (f"SELECT {id_col} AS pid, grade, datum, preis FROM {price_table} "
         f"WHERE grade IN ({','.join('?' * len(grades))}) ORDER BY pid, grade, datum")
    for row in con.execute(q, list(grades)):
        pid, grade = row["pid"], row["grade"]
        if pid not in items:
            continue
        g = grades[grade]
        cents = round(row["preis"] * 100)
        series.setdefault(pid, {}).setdefault(g, []).append([row["datum"][:7], cents])
        if grade == "used":
            latest[pid] = cents
    con.close()

    os.makedirs(os.path.join(SITE_DATA, "pc"), exist_ok=True)
    # Suchliste: [id, name, set, letzter_used_cents]
    lst = []
    for pid, it in items.items():
        if pid not in series:
            continue
        entry = [pid, it["name"] or "?", titel(it["set_slug"]), latest.get(pid),
                 it["url"]]
        if extra_cols:
            entry.append(it.get("kategorie"))
        lst.append(entry)
    lst.sort(key=lambda e: -(e[3] or 0))
    with open(os.path.join(SITE_DATA, f"{list_var.lower()}.js"), "w",
              encoding="utf-8") as f:
        f.write(f"window.{list_var}=")
        json.dump(lst, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";")

    buckets = {s: {} for s in range(shards)}
    for pid, gr in series.items():
        buckets[pid % shards][pid] = gr
    for s, data in buckets.items():
        with open(os.path.join(SITE_DATA, "pc", f"{shard_prefix}_{s}.js"), "w",
                  encoding="utf-8") as f:
            f.write(f"window.{shard_var}=window.{shard_var}||{{}};"
                    f"window.{shard_var}[{s}]=")
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.write(f";document.dispatchEvent(new CustomEvent('pcshard',"
                    f"{{detail:['{shard_prefix}',{s}]}}));")
    print(f"  -> {len(lst)} mit Historie, {shards} Shards geschrieben")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--karten", default=os.path.join(ROOT, "..", "karten.sqlite3"))
    ap.add_argument("--sealed", default=os.path.join(ROOT, "..", "sealed.sqlite3"))
    args = ap.parse_args()

    print("Karten ...")
    export(args.karten, "karten", "kartenpreise", "karte_id", CARD_GRADES,
           CARD_SHARDS, "PC_CARDS", "cards", "PC_CARD_SHARDS")
    print("Sealed ...")
    export(args.sealed, "produkte", "produktpreise", "produkt_id", SEALED_GRADES,
           SEALED_SHARDS, "PC_SEALED", "sealed", "PC_SEALED_SHARDS",
           extra_cols=", kategorie")
    return 0


if __name__ == "__main__":
    sys.exit(main())
