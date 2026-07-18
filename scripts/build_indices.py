# -*- coding: utf-8 -*-
"""
Indexberechnung nach den Regeln der Vorlage ("S&Poké 500"), angewandt auf
zwei Universen:

  SPK500  – Einzelkarten:  Top 500 nach TCGplayer Market Price
  SPKS    – Sealed:        Top 500 der Sealed-Produkte, gleiche Regeln

Regeln:
  * Preis je Produkt = Market Price des wertvollsten regulären Printings
    (1st Edition ausgeschlossen; passiert schon beim Abzug)
  * Ausreißer-Guard (nur für Anzeige/Ranking): weicht ein Tagespreis mehr
    als 2,5x nach oben oder 0,4x nach unten vom Median der letzten 14
    bestätigten Preise ab, wird er auf dem Median gehalten, bis ein
    zweiter Tag ihn bestätigt
  * Carry-Forward (nur Anzeige/Ranking): fehlt ein Preis, wird der letzte
    bekannte bis zu 70 Kalendertage fortgeschrieben (†)
  * Tagesänderung nur zwischen zwei bestätigten Preisen ("confirmed")
  * Mitglieder = Top 500 nach aktuellem (geglättetem) Preis, täglich
    fortgeschrieben
  * Index-Bewegung: winsorisierter (1 %/99 %) GLEICHGEWICHTETER Mittelwert
    der Tagesrenditen der gestrigen Mitglieder, gemessen an ROHEN
    (ungeglätteten) Preispaaren — nicht am dollar-gewichteten Preis-
    Verhältnis. Ein wert-gewichteter Ansatz reagiert überproportional auf
    einzelne teure Karten mit Datenlücken/Sprüngen (z. B. nach längeren
    Pausen ohne Verkauf); der cross-sektionale Winsor-Schnitt entschärft
    einzelne Ausreißer, ohne dass sich stateful Median-Artefakte über
    Monate aufschaukeln können. Tage mit zu wenigen validen Paaren (<20)
    lassen das Level unverändert, statt auf Rauschen zu reagieren.
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


RETURN_WINSOR = 0.01       # Cross-sektionaler Schnitt der Tagesrenditen
MIN_RETURN_PAIRS = 20      # Unter dieser Zahl valider Paare: Level halten


def compute_index(name, dates, universe, products, start_level=BASE_LEVEL):
    """universe: {pid: (adj, conf, raw)}. Liefert Ergebnis-Dict für die Website.
    start_level erlaubt das Verketten an eine vorangehende Historie (z. B.
    CS2500 an die monatliche Steam-Vorgeschichte)."""
    n = len(dates)
    series = []
    level = start_level
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
            # Bewegung = winsorisierter Mittelwert der ROHEN Tagesrenditen
            # der gestrigen Mitglieder (siehe Modulkopf für die Begründung).
            rets = []
            for pid in prev_members:
                raw_a = universe[pid][2][prev_di]
                raw_b = universe[pid][2][di]
                if raw_a and raw_b:
                    rets.append(raw_b / raw_a - 1)
            if len(rets) >= MIN_RETURN_PAIRS:
                rets.sort()
                lo = rets[int(len(rets) * RETURN_WINSOR)]
                hi = rets[min(len(rets) - 1, int(len(rets) * (1 - RETURN_WINSOR)))]
                clipped = [min(max(x, lo), hi) for x in rets]
                level = level * (1 + sum(clipped) / len(clipped))
        basket = sum(c for _, c in top) / 100.0
        adv = dec = 0
        if prev_members is not None:
            for pid in members_today:
                a, c, _raw = universe[pid]
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
        a, c, _raw = universe[pid]
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


# ------------------------------------------------------------------- CS2
import csv
import gzip

CS2_INDEX = "CS2500"
CS2_ITEMS = os.path.join(os.path.dirname(SITE_DATA), "..", "data", "cs2_items.csv.gz")
CS2_DAILY = os.path.join(os.path.dirname(SITE_DATA), "..", "data", "cs2_daily")
CS2_EW_HIST = os.path.join(os.path.dirname(SITE_DATA), "..", "data", "cs2_ew_hist.csv")
MARKETS_HIST = os.path.join(os.path.dirname(SITE_DATA), "..", "data", "markets_hist.csv")
MARKETS_RAW = os.path.join(os.path.dirname(SITE_DATA), "..", "data", "markets_raw.csv.gz")
EW_MIN_PREV_CENTS = 10        # Vormonat >= 0,10 USD (wie Masterarbeit)
EW_WINSOR = 0.01
EW_SEASON_DAYS = 183          # Seasoning-Filter: Item >= 6 Monate am Markt


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
            next(rd)
            for iid, cents, _q in rd:
                raw.setdefault(int(iid), {})[di] = int(cents)
    return dates, raw, items


def cs2_products(items):
    out = {}
    for iid, r in items.items():
        name = r["name"]
        group = name.split(" | ")[0] if " | " in name else "CS2"
        out[iid] = {"name": name, "group_name": group, "number": None,
                    "sealed_cat": None, "url": r.get("url") or None}
    return out


def cs2_ew_series(dates, raw, items):
    """EW-Index nach Masterarbeits-Methodik: Steam-Monatshistorie aus CSV,
    ab jetzt tägliche Fortführung aus den Skinport-Daten (winsorisiert,
    Seasoning-Filter). Quellenwechsel wird per Verkettung überbrückt."""
    hist = []
    if os.path.isfile(CS2_EW_HIST):
        with open(CS2_EW_HIST, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                v = r.get("idx_cs2_seasoned")
                if v:
                    hist.append([r["date"][:10], round(float(v), 2)])
    level = hist[-1][1] if hist else 100.0
    out = list(hist)
    created = {}
    for iid, r in items.items():
        try:
            created[iid] = int(float(r.get("created") or 0))
        except ValueError:
            created[iid] = 0
    for di in range(1, len(dates)):
        t = dt.date.fromisoformat(dates[di])
        t_epoch = dt.datetime(t.year, t.month, t.day).timestamp()
        rets = []
        for iid, series in raw.items():
            a, b = series.get(di - 1), series.get(di)
            if a is None or b is None or a < EW_MIN_PREV_CENTS:
                continue
            c = created.get(iid, 0)
            if c and (t_epoch - c) < EW_SEASON_DAYS * 86400:
                continue
            rets.append(b / a - 1)
        if len(rets) >= 50:
            rets.sort()
            lo = rets[int(len(rets) * EW_WINSOR)]
            hi = rets[min(len(rets) - 1, int(len(rets) * (1 - EW_WINSOR)))]
            m = sum(min(max(x, lo), hi) for x in rets) / len(rets)
            level *= (1 + m)
        out.append([dates[di], round(level, 2)])
    if dates and (not hist or dates[0] > hist[-1][0]):
        # erster Skinport-Tag als Ankerpunkt (Level unverändert)
        if not any(p[0] == dates[0] for p in out):
            out.append([dates[0], round(level if len(dates) == 1 else out[-1][1], 2)])
            out.sort()
    return out


def parse_cs2_hist_shards():
    """Liest alle site/data/cs2/hist_*.js (vom Steam-Export erzeugt) und
    liefert {item_name: [[JJJJ-MM, cents, volumen], ...]}."""
    import re
    out = {}
    cs2dir = os.path.join(SITE_DATA, "cs2")
    if not os.path.isdir(cs2dir):
        return out
    for fn in os.listdir(cs2dir):
        if not (fn.startswith("hist_") and fn.endswith(".js")):
            continue
        with open(os.path.join(cs2dir, fn), encoding="utf-8") as f:
            txt = f.read()
        m = re.search(r"CS2_HIST\[\d+\]=(\{.*\});document", txt, re.S)
        if not m:
            continue
        out.update(json.loads(m.group(1)))
    return out


CS2_HIST_MIN_BREADTH = 50   # Mindestanzahl Items/Monat, sonst kein Indexstart
                            # (gleiche Konvention wie in der Masterarbeit:
                            # "CS2 >= 50 Items" Mindestbreite). Verhindert, dass
                            # einzelne Monate mit nur 1-2 Items (z. B. 2013-04
                            # bis 2013-07, als es nur "Operation Payback Pass"
                            # gab) als degenerierter "Top 500" in die Historie
                            # einfließen und einen künstlichen Einbruch erzeugen.
CS2_HIST_START_MONTH = "2014-06"
                            # Die ersten ~10 Monate nach dem Start des Steam-
                            # Handels (Aug 2013) zeigen einen realen, aber
                            # extremen Einmal-Ausschlag: sehr wenige Items im
                            # Umlauf -> Anfangs-Knappheitspreise, die sich mit
                            # wachsendem Case-Öffnen-Angebot binnen weniger
                            # Monate stark normalisieren (Median-Rendite Aug->
                            # Sep 2013 über 395 Items: -28 %, nicht durch
                            # Ausreißer verursacht). Real, aber nicht
                            # vergleichbar mit dem gereiften Markt danach;
                            # Index startet daher erst, wenn Breite UND Zeit
                            # ausreichen.


def cs2_monthly_topn_history(hist, upto_month):
    """Monatlicher Top-500-Preisindex (gleiche Logik wie compute_index, nur
    auf Monatsbasis) aus den Steam-Monatsdaten, bis (exklusive) upto_month.
    Liefert (series, end_level) zum Verketten mit dem täglichen Skinport-Index."""
    breadth = {}
    for s in hist.values():
        for p in s:
            if p[0] < upto_month:
                breadth[p[0]] = breadth.get(p[0], 0) + 1
    months = sorted(m for m, n in breadth.items()
                    if n >= CS2_HIST_MIN_BREADTH and m >= CS2_HIST_START_MONTH)
    if not months:
        return [], BASE_LEVEL
    midx = {m: i for i, m in enumerate(months)}
    per_item = {}
    for name, s in hist.items():
        d = {}
        for m, cents, _vol in s:
            if m in midx:
                d[midx[m]] = cents
        if d:
            per_item[name] = d

    def mdiff(a, b):
        return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))

    adjusted = {}
    for name, d in per_item.items():
        arr = [None] * len(months)
        last_val, last_mi = None, None
        for mi in range(len(months)):
            if mi in d:
                arr[mi] = d[mi]; last_val, last_mi = d[mi], mi
            elif last_val is not None and mdiff(months[last_mi], months[mi]) <= 6:
                arr[mi] = last_val
        adjusted[name] = arr

    level = BASE_LEVEL
    series, prev_members, prev_mi = [], None, None
    for mi in range(len(months)):
        priced = {name: arr[mi] for name, arr in adjusted.items() if arr[mi] is not None}
        if not priced:
            continue
        top = sorted(priced.items(), key=lambda kv: (-kv[1], kv[0]))[:INDEX_SIZE]
        members_today = [name for name, _ in top]
        if prev_members is not None:
            rets = []
            for name in prev_members:
                a = per_item.get(name, {}).get(prev_mi)
                b = per_item.get(name, {}).get(mi)
                if a and b:
                    rets.append(b / a - 1)
            if len(rets) >= MIN_RETURN_PAIRS:
                rets.sort()
                lo = rets[int(len(rets) * RETURN_WINSOR)]
                hi = rets[min(len(rets) - 1, int(len(rets) * (1 - RETURN_WINSOR)))]
                clipped = [min(max(x, lo), hi) for x in rets]
                level *= (1 + sum(clipped) / len(clipped))
        series.append([months[mi] + "-01", round(level, 2)])
        prev_members, prev_mi = members_today, mi
    return series, level


def build_markets():
    if not os.path.isfile(MARKETS_HIST):
        return None
    series = {}
    with open(MARKETS_HIST, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        names = [c for c in rd.fieldnames if c != "Date"]
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
            if prev_close is not None:
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
        adj, conf = adjust(raw, dates)
        raw_list = [raw.get(di) for di in range(len(dates))]
        universes[target][pid] = (adj, conf, raw_list)

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
    # ---------------------------------------------------------------- CS2
    cdates, craw, citems = load_cs2()
    if cdates:
        cprod = cs2_products(citems)
        cuniv = {}
        for iid, r in craw.items():
            adj, conf = adjust(r, cdates)
            raw_list = [r.get(di) for di in range(len(cdates))]
            cuniv[iid] = (adj, conf, raw_list)
        # Monatliche Top-500-Vorgeschichte aus den Steam-Daten (2014-heute)
        # an den täglichen Skinport-Index verketten, statt bei 1000 zu starten.
        hist_data = parse_cs2_hist_shards()
        hist_series, hist_end_level = cs2_monthly_topn_history(hist_data, cdates[0])
        res = compute_index(CS2_INDEX, cdates, cuniv, cprod, start_level=hist_end_level)
        if res is not None:
            res["series"] = hist_series + res["series"]
            levels = [p[1] for p in res["series"]]
            res["overview"]["ath"] = max(levels)
            res["overview"]["atl"] = min(levels)
            res["hist_source_note"] = (
                f"Historie bis {cdates[0]} aus Steam-Monatsdaten (Top 500 nach "
                f"Preis, gleiche Methodik wie der Tagesindex); ab {cdates[0]} "
                f"täglich aus Skinport, nahtlos verkettet.")
            res["ew"] = cs2_ew_series(cdates, craw, citems)
            with open(os.path.join(SITE_DATA, "idx_CS2.js"), "w",
                      encoding="utf-8") as f:
                f.write("window.IDX_CS2=")
                json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
                f.write(";")
            summary[CS2_INDEX] = {
                "asof": res["asof"], "overview": res["overview"],
                "series_tail": res["series"][-30:],
                "ew_tail": res["ew"][-40:],
                "weekly_up": res["weekly_up"], "weekly_dn": res["weekly_dn"],
                "gainers": res["gainers"][:5], "losers": res["losers"][:5],
            }
            o = res["overview"]
            print(f"{CS2_INDEX}: Stand {res['asof']}  Level {o['level']}  "
                  f"Basket ${o['basket']:,}  {len(res['rows'])} Mitglieder")

    # -------------------------------------------------------------- Märkte
    mk = build_markets()
    if mk is not None:
        with open(os.path.join(SITE_DATA, "markets.js"), "w",
                  encoding="utf-8") as f:
            f.write("window.MARKETS=")
            json.dump(mk, f, ensure_ascii=False, separators=(",", ":"))
            f.write(";")
        summary["MARKETS"] = mk["changes"]
        print("Märkte:", ", ".join(
            f"{n} {c['level']:,}" for n, c in sorted(mk["changes"].items())))

    with open(os.path.join(SITE_DATA, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
