# -*- coding: utf-8 -*-
"""Indexberechnung: SPK500 (Einzelkarten), SPKS (Sealed), CS2500 (CS2-Skins).

Die Fachlogik liegt in pokedata/indexlib.py und wird von allen Konsumenten
geteilt (vorher gab es zwei abweichende Indexdefinitionen im Projekt).
Dieses Skript ist nur noch Verdrahtung: Daten laden, Regeln anwenden,
validieren, Artefakte schreiben.

Regeln (Details und Begründungen: pokedata/indexlib.py):
  * Bereinigung je Produkt (Ausreißer-Guard + Carry-Forward) nur für Anzeige,
    Ranking und Mitgliederauswahl.
  * Indexbewegung = winsorisierter gleichgewichteter Mittelwert der ROHEN
    Tagesrenditen der gestrigen Mitglieder. Kein Divisor-Verfahren – die
    frühere README-Beschreibung war an dieser Stelle falsch.
  * Printing-Guard: Renditepaare mit gewechseltem Printing (sub_type) werden
    verworfen, statt eine Scheinrendite zu erzeugen.
  * Mindestbreite 20 % der Indexgröße, sonst bleibt das Niveau unverändert.
  * Die komplette Historie wird bei jedem Lauf deterministisch neu gerechnet.

Ausgabe: site/data/idx_*.js, site/data/markets.js, site/data/summary.json
Aufruf:  python scripts/build_indices.py [--strict]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import re
import sys

from common import (
    BASE_LEVEL,
    CARD_INDEX,
    CS2_INDEX,
    DATA_DIR,
    INDEX_RULES,
    SEALED_INDEX,
    SITE_DATA,
    have_dates,
    read_daily,
    read_products,
)

from pokedata import METHOD_VERSION, indexlib, quality
from pokedata.atomicio import write_js_var, write_json

CS2_ITEMS = os.path.join(DATA_DIR, "cs2_items.csv.gz")
CS2_DAILY = os.path.join(DATA_DIR, "cs2_daily")
CS2_EW_HIST = os.path.join(DATA_DIR, "cs2_ew_hist.csv")
MARKETS_HIST = os.path.join(DATA_DIR, "markets_hist.csv")
MARKETS_RAW = os.path.join(DATA_DIR, "markets_raw.csv.gz")

# CS2-EW-Parameter (Masterarbeits-Methodik)
EW_MIN_PREV_CENTS = 10          # Vormonat >= 0,10 USD
EW_WINSOR = 0.01
EW_SEASON_DAYS = 183            # Item mindestens 6 Monate am Markt
EW_MIN_PAIRS = 50

CS2_HIST_MIN_BREADTH = 50
CS2_HIST_START_MONTH = "2014-06"
# Begründung (aus der Masterarbeit): Die ersten ~10 Monate nach Start des
# Steam-Handels (Aug 2013) zeigen einen realen, aber extremen Einmal-Ausschlag
# – sehr wenige Items im Umlauf, Anfangsknappheit, die sich mit wachsendem
# Angebot binnen Monaten normalisiert (Medianrendite Aug->Sep 2013 über 395
# Items: -28 %). Real, aber nicht mit dem gereiften Markt vergleichbar.


# ------------------------------------------------------------------ Karten
def load_series():
    """(dates, {pid: {di: cents}}, {pid: {di: sub_type}})."""
    dates = have_dates()
    per_product, variants = {}, {}
    for di, d in enumerate(dates):
        for pid, cents, sub in read_daily(d):
            per_product.setdefault(pid, {})[di] = cents
            variants.setdefault(pid, {})[di] = sub
    return dates, per_product, variants


# --------------------------------------------------------------------- CS2
def load_cs2():
    if not os.path.isdir(CS2_DAILY):
        return [], {}, {}
    items = {}
    if os.path.isfile(CS2_ITEMS):
        with gzip.open(CS2_ITEMS, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                items[int(r["item_id"])] = r
    dates = sorted(f[:-7] for f in os.listdir(CS2_DAILY) if f.endswith(".csv.gz"))
    raw = {}
    for di, d in enumerate(dates):
        with gzip.open(os.path.join(CS2_DAILY, f"{d}.csv.gz"), "rt",
                       encoding="utf-8", newline="") as f:
            rd = csv.reader(f)
            next(rd, None)
            for iid, cents, _q in rd:
                raw.setdefault(int(iid), {})[di] = int(cents)
    return dates, raw, items


def cs2_products(items: dict) -> dict:
    out = {}
    for iid, r in items.items():
        name = r["name"]
        group = name.split(" | ")[0] if " | " in name else "CS2"
        out[iid] = {"name": name, "group_name": group, "number": None,
                    "sealed_cat": None, "url": r.get("url") or None}
    return out


def cs2_ew_series(dates, raw, items):
    """EW-Index: Steam-Monatshistorie + tägliche Skinport-Fortführung.

    Der Quellenwechsel (Steam-Verkäufe -> Skinport-Angebote) wird per
    Verkettung überbrückt und im Ergebnis als `splice` gekennzeichnet: die
    Niveauhöhe ist stetig, die Preisart wechselt aber von Transaktions- auf
    Angebotspreise. Zwischen dem letzten Monatspunkt und dem ersten Tagespunkt
    liegt zudem eine Erhebungslücke, die nicht modelliert wird.
    """
    hist = []
    if os.path.isfile(CS2_EW_HIST):
        with open(CS2_EW_HIST, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                v = r.get("idx_cs2_seasoned")
                if v:
                    hist.append([r["date"][:10], round(float(v), 2)])
    level = hist[-1][1] if hist else 100.0
    created = {}
    for iid, r in items.items():
        try:
            created[iid] = int(float(r.get("created") or 0))
        except (TypeError, ValueError):
            created[iid] = 0

    def eligible(iid, di):
        prev = raw.get(iid, {}).get(di - 1)
        if prev is None or prev < EW_MIN_PREV_CENTS:
            return False
        c = created.get(iid, 0)
        if c:
            t = dt.date.fromisoformat(dates[di])
            t_epoch = dt.datetime(t.year, t.month, t.day,
                                  tzinfo=dt.timezone.utc).timestamp()
            if (t_epoch - c) < EW_SEASON_DAYS * 86400:
                return False
        return True

    daily = indexlib.ew_chain(dates, raw, start_level=level, winsor=EW_WINSOR,
                             min_pairs=EW_MIN_PAIRS, eligible=eligible)
    splice = None
    if hist and dates:
        gap = (dt.date.fromisoformat(dates[0])
               - dt.date.fromisoformat(hist[-1][0])).days
        splice = {"letzter_monatspunkt": hist[-1][0],
                  "erster_tagespunkt": dates[0],
                  "luecke_tage": gap,
                  "quellenwechsel": "Steam-Verkaufspreise -> Skinport-Angebote (Ask)",
                  "hinweis": ("Niveau stetig verkettet; Preisart und Erhebung "
                              "wechseln an dieser Stelle.")}
    out = list(hist)
    for p in daily:
        if not out or p[0] > out[-1][0]:
            out.append(p)
    return out, splice


def parse_cs2_hist_shards():
    """site/data/cs2/hist_*.js -> {item_name: [[JJJJ-MM, cents, volumen], ...]}"""
    out = {}
    cs2dir = os.path.join(SITE_DATA, "cs2")
    if not os.path.isdir(cs2dir):
        return out
    for fn in sorted(os.listdir(cs2dir)):
        if not (fn.startswith("hist_") and fn.endswith(".js")):
            continue
        with open(os.path.join(cs2dir, fn), encoding="utf-8") as f:
            txt = f.read()
        m = re.search(r"CS2_HIST\[\d+\]=(\{.*\});document", txt, re.S)
        if not m:
            continue
        out.update(json.loads(m.group(1)))
    return out


# ------------------------------------------------------------------ Märkte
def build_markets():
    if not os.path.isfile(MARKETS_HIST):
        return None
    series = {}
    with open(MARKETS_HIST, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        names = [c for c in (rd.fieldnames or []) if c != "Date"]
        for r in rd:
            for n in names:
                v = r.get(n)
                if v:
                    series.setdefault(n, []).append([r["Date"], float(v)])
    raw = {}
    if os.path.isfile(MARKETS_RAW):
        with gzip.open(MARKETS_RAW, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                raw.setdefault(r["series"], []).append((r["date"], float(r["close"])))
    for n, lst in series.items():
        lst.sort()
        last_d, level = lst[-1]
        prev_close = None
        for d, c in sorted(raw.get(n, [])):
            if d <= last_d:
                prev_close = c
                continue
            if prev_close is not None and prev_close > 0:
                level = level * (c / prev_close)
                lst.append([d, round(level, 4)])
            prev_close = c
    changes = {}
    for n, lst in series.items():
        lvl = lst[-1][1]
        d1 = (lvl / lst[-2][1] - 1) * 100 if len(lst) > 1 else None
        last = dt.date.fromisoformat(lst[-1][0])
        w = [p for p in lst if (last - dt.date.fromisoformat(p[0])).days >= 7]
        w1 = (lvl / w[-1][1] - 1) * 100 if w else None
        changes[n] = {"level": round(lvl, 2), "asof": lst[-1][0],
                      "d1": round(d1, 2) if d1 is not None else None,
                      "w1": round(w1, 2) if w1 is not None else None}
    return {"series": {n: [[d, round(v, 2)] for d, v in lst]
                       for n, lst in series.items()},
            "changes": changes}


# -------------------------------------------------------------------- Lauf
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="bei Validierungsfehlern mit Exitcode 1 enden")
    args = ap.parse_args()

    rep = quality.Report()
    products = read_products()
    dates, per_product, variants = load_series()
    if not dates:
        print("Keine Tagesdaten vorhanden – zuerst fetch_prices.py ausführen.")
        return 1
    print(f"{len(dates)} Datentage, {len(per_product)} Produkte mit Preisen")
    quality.check_date_gaps(dates, rep, "Karten-Tagesreihe")

    universes = {CARD_INDEX: {}, SEALED_INDEX: {}}
    split = {CARD_INDEX: {}, SEALED_INDEX: {}}
    split_var = {CARD_INDEX: {}, SEALED_INDEX: {}}
    for pid, raw in per_product.items():
        p = products.get(pid)
        if p is None:
            continue
        target = CARD_INDEX if p["is_sealed"] == 0 else SEALED_INDEX
        split[target][pid] = raw
        split_var[target][pid] = variants.get(pid, {})
    for name in (CARD_INDEX, SEALED_INDEX):
        universes[name] = indexlib.build_universe(split[name], dates,
                                                 INDEX_RULES, split_var[name])

    from common import KEEP_STORE_PRICE, MIN_STORE_PRICE
    quality.censoring_report(split[CARD_INDEX], dates,
                             int(MIN_STORE_PRICE * 100),
                             int(KEEP_STORE_PRICE * 100), rep)

    os.makedirs(SITE_DATA, exist_ok=True)
    summary = {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "method_version": METHOD_VERSION,
        "rules": INDEX_RULES.as_dict(),
    }
    results = {}
    for idx_name, var in ((CARD_INDEX, "IDX_CARDS"), (SEALED_INDEX, "IDX_SEALED")):
        res = indexlib.compute_index(idx_name, dates, universes[idx_name],
                                     products, INDEX_RULES)
        if res is None:
            rep.error(f"{idx_name}: keine Daten")
            continue
        quality.check_index_result(res, rep, idx_name)
        results[idx_name] = res
        write_js_var(os.path.join(SITE_DATA, f"idx_{idx_name}.js"), var, res)
        summary[idx_name] = {
            "asof": res["asof"], "overview": res["overview"],
            "series_tail": res["series"][-30:],
            "weekly_up": res["weekly_up"], "weekly_dn": res["weekly_dn"],
            "gainers": res["gainers"][:5], "losers": res["losers"][:5],
            "diagnostics": res["diagnostics"],
        }
        o = res["overview"]
        print(f"{idx_name}: Stand {res['asof']}  Level {o['level']}  "
              f"Basket ${o['basket']:,}  {len(res['rows'])} Mitglieder  "
              f"(Printing-Paare verworfen: "
              f"{res['diagnostics']['variant_pairs_dropped']})")

    # ---------------------------------------------------------------- CS2
    cdates, craw, citems = load_cs2()
    if cdates:
        quality.check_date_gaps(cdates, rep, "CS2-Tagesreihe")
        cprod = cs2_products(citems)
        cuniv = indexlib.build_universe(craw, cdates, INDEX_RULES)
        hist_data = parse_cs2_hist_shards()
        hist_series, hist_end_level = indexlib.monthly_topn_chain(
            hist_data, cdates[0], INDEX_RULES,
            min_breadth=CS2_HIST_MIN_BREADTH,
            start_month=CS2_HIST_START_MONTH)
        res = indexlib.compute_index(CS2_INDEX, cdates, cuniv, cprod,
                                     INDEX_RULES,
                                     start_level=hist_end_level or BASE_LEVEL)
        if res is not None:
            res["series"] = hist_series + res["series"]
            levels = [p[1] for p in res["series"]]
            res["overview"]["ath"] = max(levels)
            res["overview"]["atl"] = min(levels)
            splice_top = None
            if hist_series and cdates:
                gap = (dt.date.fromisoformat(cdates[0])
                       - dt.date.fromisoformat(hist_series[-1][0])).days
                splice_top = {"letzter_monatspunkt": hist_series[-1][0],
                              "erster_tagespunkt": cdates[0],
                              "luecke_tage": gap}
            res["hist_source_note"] = (
                f"Historie bis {cdates[0]} aus Steam-Monatsdaten (Top 500 nach "
                f"Preis, gleiche Methodik wie der Tagesindex); ab {cdates[0]} "
                f"täglich aus Skinport (Angebotsmediane), verkettet.")
            ew, ew_splice = cs2_ew_series(cdates, craw, citems)
            res["ew"] = ew
            res["splice"] = {"topn": splice_top, "ew": ew_splice}
            ew_levels = [p[1] for p in ew]
            ew_level = ew[-1][1] if ew else None
            ew_prev = ew[-2][1] if len(ew) > 1 else None
            res["ew_overview"] = {
                "level": ew_level, "prev": ew_prev,
                "chg": (round((ew_level / ew_prev - 1) * 100, 2)
                        if ew_prev else None),
                "ath": max(ew_levels) if ew_levels else None,
                "atl": min(ew_levels) if ew_levels else None,
                "asof": ew[-1][0] if ew else None,
            }
            quality.check_index_result(res, rep, CS2_INDEX)
            if splice_top and splice_top["luecke_tage"] > 7:
                rep.warn(f"CS2: {splice_top['luecke_tage']} Tage Erhebungslücke "
                         f"zwischen Monats- und Tagesdaten "
                         f"({splice_top['letzter_monatspunkt']} -> "
                         f"{splice_top['erster_tagespunkt']})")
            results[CS2_INDEX] = res
            write_js_var(os.path.join(SITE_DATA, "idx_CS2.js"), "IDX_CS2", res)
            summary[CS2_INDEX] = {
                "asof": res["asof"], "overview": res["overview"],
                "series_tail": res["series"][-30:],
                "ew_tail": res["ew"][-40:], "ew_overview": res["ew_overview"],
                "weekly_up": res["weekly_up"], "weekly_dn": res["weekly_dn"],
                "gainers": res["gainers"][:5], "losers": res["losers"][:5],
                "splice": res["splice"], "diagnostics": res["diagnostics"],
            }
            print(f"{CS2_INDEX}: Stand {res['asof']}  Level "
                  f"{res['overview']['level']}  | EW-Index {ew_level}")

    # ------------------------------------------------------------- Märkte
    mk = build_markets()
    if mk is not None:
        write_js_var(os.path.join(SITE_DATA, "markets.js"), "MARKETS", mk)
        summary["MARKETS"] = mk["changes"]
        stale = [n for n, c in mk["changes"].items()
                 if (dt.date.today() - dt.date.fromisoformat(c["asof"])).days > 5]
        if stale:
            rep.warn(f"Marktreihen ohne frische Kurse: {', '.join(sorted(stale))}")
        print("Märkte:", ", ".join(f"{n} {c['level']:,}"
                                   for n, c in sorted(mk["changes"].items())))

    write_json(os.path.join(SITE_DATA, "summary.json"), summary)

    print("\nValidierung:")
    print(rep.render())
    write_json(os.path.join(SITE_DATA, "quality.json"),
               {"built": summary["built"], "errors": rep.errors,
                "warnings": rep.warnings, "info": rep.info})
    if rep.failed and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
