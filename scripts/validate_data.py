# -*- coding: utf-8 -*-
"""Datenvalidierung als eigener Schritt – der Wächter der Pipeline.

Wird im Workflow VOR dem Deploy ausgeführt. Findet Lücken, Zeilenzahl-Brüche,
unplausible Preise, veraltete Reihen und inkonsistente Artefakte. Mit
`--strict` endet der Lauf bei Fehlern mit Exitcode 1, sodass kein fehlerhafter
Datenstand veröffentlicht wird.

Aufruf:
  python scripts/validate_data.py            # Bericht
  python scripts/validate_data.py --strict   # Fehler brechen den Lauf ab
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import os
import sys

from common import (
    CARD_INDEX,
    CS2_INDEX,
    DATA_DIR,
    SEALED_INDEX,
    SITE_DATA,
    have_dates,
    read_daily,
    read_products,
)

from pokedata import quality
from pokedata.atomicio import read_js_var, write_json

# Höchstalter je Datenquelle. WICHTIG ist die Abstufung dahinter:
#
#   KERN      Karten/Sealed (tcgcsv) und die daraus gebauten Indizes SPK500 und
#             SPKS. Sind die kaputt, darf nichts veröffentlicht werden.
#   NEBEN     CS2 (Skinport) und die Marktreihen. Fällt eine dieser Quellen
#             zeitweise aus, ist das ärgerlich, aber kein Grund, die intakten
#             Pokémon-Daten nicht zu veröffentlichen.
#
# Die erste Fassung behandelte alles gleich streng – ein Skinport-Ausfall
# blockierte damit den gesamten Deploy inklusive einwandfreier Kartendaten.
MAX_AGE_DAYS = {"karten": 3, "cs2": 3, "markets": 6, "index": 3}

# Ab diesem Alter gilt auch eine Nebenquelle als echter Fehler: dann ist nicht
# mehr von einem vorübergehenden Ausfall auszugehen.
AUX_HARD_AGE_DAYS = 30

AUX_INDICES = {CS2_INDEX}


def melde_alter(rep, name: str, age: int, grenze: int, kern: bool,
                zusatz: str = "") -> None:
    """Altersmeldung mit korrekter Schwere (Kern = Fehler, Neben = Warnung)."""
    if age <= grenze:
        return
    text = f"{name}: Datenstand {age} Tage alt (erlaubt: {grenze})"
    if zusatz:
        text += f" – {zusatz}"
    if kern or age > AUX_HARD_AGE_DAYS:
        rep.error(text)
    else:
        rep.warn(text + " – Nebenquelle, Veröffentlichung läuft weiter")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--today", default=dt.date.today().isoformat(),
                    help="Referenzdatum (für Tests)")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today)
    rep = quality.Report()

    # ---- Tagesdateien Karten/Sealed ----
    dates = have_dates()
    quality.check_date_gaps(dates, rep, "Karten-Tagesreihe")
    if dates:
        age = (today - dt.date.fromisoformat(dates[-1])).days
        rep.info["Karten-Datenstand"] = f"{dates[-1]} ({age} Tage alt)"
        melde_alter(rep, "Karten-Tagesdaten", age, MAX_AGE_DAYS["karten"],
                    kern=True, zusatz="läuft der tägliche Workflow?")
        counts = {}
        for d in dates[-15:]:
            try:
                rows = read_daily(d)
            except OSError as exc:
                rep.error(f"Tagesdatei {d} nicht lesbar: {exc}")
                continue
            counts[d] = len(rows)
            if d == dates[-1]:
                quality.check_prices(rows, rep, label=f"Preise {d}")
        quality.check_rowcount(counts, rep, label="Tagesdatei")
        empty = [d for d, n in counts.items() if n == 0]
        if empty:
            rep.warn(f"leere Tagesdateien: {', '.join(empty[:5])}")

    # ---- Stammdaten ----
    products = read_products()
    rep.info["Stammdaten"] = f"{len(products)} Produkte"
    if not products:
        rep.error("products.csv.gz fehlt oder ist leer")
    else:
        ohne_gruppe = sum(1 for p in products.values() if not p.get("group_name"))
        if ohne_gruppe:
            rep.warn(f"{ohne_gruppe} Produkte ohne Set-Zuordnung")

    # ---- CS2 ----
    cs2_dir = os.path.join(DATA_DIR, "cs2_daily")
    if os.path.isdir(cs2_dir):
        cdates = sorted(f[:-7] for f in os.listdir(cs2_dir) if f.endswith(".csv.gz"))
        quality.check_date_gaps(cdates, rep, "CS2-Tagesreihe")
        if cdates:
            age = (today - dt.date.fromisoformat(cdates[-1])).days
            rep.info["CS2-Datenstand"] = f"{cdates[-1]} ({age} Tage alt)"
            melde_alter(rep, "CS2-Daten", age, MAX_AGE_DAYS["cs2"], kern=False,
                        zusatz="Skinport-Abruf prüfen")
            with gzip.open(os.path.join(cs2_dir, f"{cdates[-1]}.csv.gz"), "rt") as f:
                n = sum(1 for _ in f) - 1
            if n < 1000:
                rep.warn(f"CS2-Tagesdatei {cdates[-1]} enthält nur {n} Items")

    # ---- Marktreihen ----
    mpath = os.path.join(SITE_DATA, "markets.js")
    if os.path.isfile(mpath):
        mk = read_js_var(mpath)
        for name, c in (mk.get("changes") or {}).items():
            age = (today - dt.date.fromisoformat(c["asof"])).days
            if age > MAX_AGE_DAYS["markets"]:
                rep.warn(f"Marktreihe {name}: letzter Kurs {c['asof']} "
                         f"({age} Tage alt)")
    else:
        rep.warn("markets.js fehlt")

    # ---- Indexartefakte ----
    for name, fn in ((CARD_INDEX, "idx_SPK500.js"), (SEALED_INDEX, "idx_SPKS.js"),
                     (CS2_INDEX, "idx_CS2.js")):
        path = os.path.join(SITE_DATA, fn)
        if not os.path.isfile(path):
            rep.error(f"{name}: {fn} fehlt – build_indices.py ausführen")
            continue
        try:
            data = read_js_var(path)
        except Exception as exc:                          # noqa: BLE001
            rep.error(f"{name}: {fn} nicht lesbar ({exc})")
            continue
        quality.check_index_result(data, rep, name)
        age = (today - dt.date.fromisoformat(data["asof"])).days
        melde_alter(rep, name, age, MAX_AGE_DAYS["index"],
                    kern=(name not in AUX_INDICES))
        # Reihe muss monoton in der Zeit und lückenfrei interpretierbar sein
        ds = [d for d, _v in data["series"]]
        if ds != sorted(ds):
            rep.error(f"{name}: Zeitreihe ist nicht chronologisch sortiert")
        if len(set(ds)) != len(ds):
            rep.error(f"{name}: doppelte Datumswerte in der Zeitreihe")

    out = {"geprueft": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "referenzdatum": args.today,
           "errors": rep.errors, "warnings": rep.warnings, "info": rep.info}
    os.makedirs(SITE_DATA, exist_ok=True)
    write_json(os.path.join(SITE_DATA, "quality.json"), out)

    print("Datenvalidierung:")
    print(rep.render())
    print(f"\n{len(rep.errors)} Fehler, {len(rep.warnings)} Warnungen")
    if rep.failed and args.strict:
        print("STRICT: Abbruch – kein Deploy mit diesem Datenstand.")
        print("Nur KERN-Probleme (Karten/Sealed und ihre Indizes) brechen ab; "
              "eine ausgefallene Nebenquelle erzeugt nur eine Warnung.")
        return 1
    if rep.warnings:
        print("Veröffentlichung läuft weiter – die Warnungen stehen in "
              "site/data/quality.json und auf der Website.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
