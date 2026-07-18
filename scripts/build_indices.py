# -*- coding: utf-8 -*-
"""
Indexberechnung nach den Regeln der Vorlage ("S&Poké 500"), angewandt auf
zwei Universen:

  SPK500  – Einzelkarten:  Top 500 nach TCGplayer Market Price
  SPKS    – Sealed:        Top 500 der Sealed-Produkte, gleiche Regeln

Regeln:
  * Preis je Produkt = Market Price des wertvollsten regulären Printings
    (1st Edition ausgeschlossen; passiert schon beim Abzug)
  * Ausreißer-Guard: weicht ein Tagespreis mehr als 2,5x nach oben oder
    0,4x nach unten vom Median der letzten 14 bestätigten Preise ab, wird
    er auf dem Median gehalten, bis ein zweiter Tag ihn bestätigt
  * Carry-Forward: fehlt ein Preis, wird der letzte bekannte bis zu 70
    Kalendertage fortgeschrieben (†); danach fällt das Produkt heraus
  * Tagesänderung nur zwischen zwei bestätigten Preisen ("confirmed")
  * Mitglieder = Top 500 nach aktuellem Preis, täglich fortgeschrieben;
    Index-Level bleibt über Mitgliederwechsel hinweg stetig (Divisor-Logik)
  * Startniveau 1000 am ersten Datentag

Die komplette Historie wird bei jedem Lauf deterministisch neu gerechnet
(keine persistenten Zwischenstände). Ausgabe: site/data/idx_*.js und
site/data/summary.json (für Newsletter).

Aufruf:  python scripts/build_indices.py
"""
import datetime as dt
import json
import os
import statistics
import sys

from common import (BASE_LEVEL, CARD_INDEX, CARRY_MAX_DAYS, INDEX_SIZE,
                    OUTLIER_HI, OUTLIER_LO, OUTLIER_MIN_HISTORY,
                    OUTLIER_WINDOW, SEALED_INDEX, SITE_DATA, have_dates,
                    read_daily, read_products)


def load_series():
    """dates (sortiert) und {pid: {dateindex: cents}}."""
    dates = have_dates()
    per_product = {}
    for di, d in enumerate(dates):
        for pid, cents, _sub in read_daily(d):
            per_product.setdefault(pid, {})[di] = cents
    return dates, per_product


def adjust(raw, dates):
    """Ausreißer-Guard + Carry-Forward für ein Produkt.
    raw: {dateindex: cents} -> (adj, confirmed) Listen über alle dateindexe."""
    n = len(dates)
    adj = [None] * n
    conf = [False] * n
    hist = []            # bestätigte Preise
    dev_run = 0
    last_val, last_di = None, None
    date_objs = [dt.date.fromisoformat(d) for d in dates]
    for di in range(n):
        r = raw.get(di)
        if r is not None:
            suspicious = False
            if len(hist) >= OUTLIER_MIN_HISTORY:
                med = statistics.median(hist[-OUTLIER_WINDOW:])
                if r > med * OUTLIER_HI or r < med * OUTLIER_LO:
                    suspicious = dev_run < 1   # zweiter Ausreißertag bestätigt
            if suspicious:
                dev_run += 1
                med = statistics.median(hist[-OUTLIER_WINDOW:])
                adj[di] = int(med)
                conf[di] = False
                last_val, last_di = int(med), di
            else:
                dev_run = 0
                adj[di] = r
                conf[di] = True
                hist.append(r)
                last_val, last_di = r, di
        else:
            dev_run = 0
            if last_val is not None and \
               (date_objs[di] - date_objs[last_di]).days <= CARRY_MAX_DAYS:
                adj[di] = last_val
                conf[di] = False
    return adj, conf


def img_url(pid):
    return f"https://tcgplayer-cdn.tcgplayer.com/product/{pid}_in_200x200.jpg"


def compute_index(name, dates, universe, products):
    """universe: {pid: (adj, conf)}. Liefert Ergebnis-Dict für die Website."""
    n = len(dates)
    series = []
    level = BASE_LEVEL
    prev_members = None
    members = None
    adv = dec = 0
    for di in range(n):
        priced = {pid: u[0][di] for pid, u in universe.items() if u[0][di] is not None}
        if not priced:
            continue
        top = sorted(priced.items(), key=lambda kv: (-kv[1], kv[0]))[:INDEX_SIZE]
        members_today = [pid for pid, _ in top]
        if prev_members is not None:
            common = [pid for pid in prev_members
                      if universe[pid][0][di] is not None and
                      universe[pid][0][prev_di] is not None]
            s_prev = sum(universe[pid][0][prev_di] for pid in common)
            s_now = sum(universe[pid][0][di] for pid in common)
            if s_prev > 0:
                level = level * (s_now / s_prev)
        basket = sum(c for _, c in top) / 100.0
        adv = dec = 0
        if prev_members is not None:
            for pid in members_today:
                a, c = universe[pid]
                if c[di] and c[prev_di] and a[prev_di]:
                    if a[di] > a[prev_di]:
                        adv += 1
                    elif a[di] < a[prev_di]:
                        dec += 1
        series.append({"d": dates[di], "l": round(level, 2),
                       "b": round(basket), "a": adv, "e": dec})
        prev_members, prev_di, members = members_today, di, top
    if not series:
        return None

    last_di = dates.index(series[-1]["d"])
    prev_di_glob = dates.index(series[-2]["d"]) if len(series) > 1 else None
    member_set_prev = set()
    if len(series) > 1:
        # Mitglieder des Vortags noch einmal bestimmen (für "NEU"-Flag)
        priced_prev = {pid: u[0][prev_di_glob] for pid, u in universe.items()
                       if u[0][prev_di_glob] is not None}
        member_set_prev = {pid for pid, _ in sorted(
            priced_prev.items(), key=lambda kv: (-kv[1], kv[0]))[:INDEX_SIZE]}

    def week_anchor():
        last = dt.date.fromisoformat(dates[last_di])
        for di in range(last_di, -1, -1):
            if (last - dt.date.fromisoformat(dates[di])).days >= 7:
                return di
        return None

    wk_di = week_anchor()

    rows, movers = [], []
    for rank, (pid, cents) in enumerate(members, 1):
        a, c = universe[pid]
        p = products.get(pid, {})
        chg = None
        if prev_di_glob is not None and c[last_di] and c[prev_di_glob] and a[prev_di_glob]:
            chg = round((a[last_di] / a[prev_di_glob] - 1) * 100, 2)
        wchg = None
        if wk_di is not None and c[last_di] and c[wk_di] and a[wk_di]:
            wchg = round((a[last_di] / a[wk_di] - 1) * 100, 2)
        row = {"id": pid, "r": rank, "n": p.get("name", "?"),
               "s": p.get("group_name", ""), "num": p.get("number"),
               "p": cents / 100.0, "chg": chg, "wchg": wchg,
               "car": 0 if c[last_di] else 1,
               "new": 1 if (member_set_prev and pid not in member_set_prev) else 0,
               "cat": p.get("sealed_cat"), "u": p.get("url")}
        rows.append(row)
        if chg is not None and chg != 0:
            movers.append(row)

    movers.sort(key=lambda r: r["chg"], reverse=True)
    gainers = movers[:6]
    losers = sorted(movers, key=lambda r: r["chg"])[:6]
    wk = [r for r in rows if r["wchg"] is not None and r["wchg"] != 0]
    wk_up = sorted(wk, key=lambda r: r["wchg"], reverse=True)[:5]
    wk_dn = sorted(wk, key=lambda r: r["wchg"])[:5]

    levels = [s["l"] for s in series]
    out = {
        "name": name,
        "asof": series[-1]["d"],
        "series": [[s["d"], s["l"]] for s in series],
        "overview": {
            "level": series[-1]["l"],
            "prev": series[-2]["l"] if len(series) > 1 else None,
            "ath": max(levels), "atl": min(levels),
            "basket": series[-1]["b"],
            "adv": series[-1]["a"], "dec": series[-1]["e"],
        },
        "gainers": gainers, "losers": losers,
        "weekly_up": wk_up, "weekly_dn": wk_dn,
        "rows": rows,
    }
    return out


def main():
    products = read_products()
    dates, per_product = load_series()
    if not dates:
        print("Keine Tagesdaten vorhanden – zuerst fetch_prices.py ausführen.")
        return 1
    print(f"{len(dates)} Datentage, {len(per_product)} Produkte mit Preisen")

    universes = {CARD_INDEX: {}, SEALED_INDEX: {}}
    for pid, raw in per_product.items():
        p = products.get(pid)
        if p is None:
            continue
        target = CARD_INDEX if p["is_sealed"] == 0 else SEALED_INDEX
        universes[target][pid] = adjust(raw, dates)

    os.makedirs(SITE_DATA, exist_ok=True)
    summary = {"built": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"}
    for idx_name, var in ((CARD_INDEX, "IDX_CARDS"), (SEALED_INDEX, "IDX_SEALED")):
        res = compute_index(idx_name, dates, universes[idx_name], products)
        if res is None:
            print(f"{idx_name}: keine Daten")
            continue
        path = os.path.join(SITE_DATA, f"idx_{idx_name}.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"window.{var}=")
            json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
            f.write(";")
        summary[idx_name] = {
            "asof": res["asof"], "overview": res["overview"],
            "series_tail": res["series"][-30:],
            "weekly_up": res["weekly_up"], "weekly_dn": res["weekly_dn"],
            "gainers": res["gainers"][:5], "losers": res["losers"][:5],
        }
        o = res["overview"]
        print(f"{idx_name}: Stand {res['asof']}  Level {o['level']}  "
              f"Basket ${o['basket']:,}  {len(res['rows'])} Mitglieder")
    with open(os.path.join(SITE_DATA, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
