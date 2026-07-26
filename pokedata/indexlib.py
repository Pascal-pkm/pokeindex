# -*- coding: utf-8 -*-
"""Indexbibliothek – ein Regelwerk für alle Indizes des Projekts.

Enthält die Logik, die vorher in scripts/build_indices.py (Top-N, Guard,
Winsor) und parallel, aber abweichend, in pokemon-sealed-dashboard/backend/
indices.py (EW, Basis 100, ohne Guard) implementiert war.

Methodik Top-N-Kettenindex (SPK500, SPKS, CS2500)
------------------------------------------------
1. Bereinigung je Produkt (`adjust`), NUR für Anzeige, Ranking und
   Mitgliederauswahl:
     * Ausreißer-Guard: liegt ein Tagespreis über `outlier_hi` bzw. unter
       `outlier_lo` mal dem Median der letzten `outlier_window` bestätigten
       Preise, wird der Median gehalten, bis ein zweiter Tag den Wert
       bestätigt. Der Tag gilt als "unbestätigt".
     * Carry-Forward: fehlt ein Preis, wird der letzte bekannte bis
       `carry_max_days` Kalendertage fortgeschrieben ("unbestätigt").
2. Mitglieder = Top `size` nach bereinigtem Preis, täglich neu bestimmt.
3. Indexbewegung = winsorisierter (`return_winsor`) gleichgewichteter
   Mittelwert der Tagesrenditen der GESTRIGEN Mitglieder, gemessen an ROHEN
   Preispaaren. Begründung: ein wertgewichteter Ansatz reagiert
   überproportional auf einzelne teure Positionen mit Datenlücken; der
   Querschnitts-Winsor entschärft Einzelausreißer, ohne dass sich
   Median-Artefakte über Monate aufschaukeln (wie es ein stateful Guard in
   der Renditeberechnung täte). Weniger als `min_return_pairs` valide Paare
   lassen das Niveau unverändert.
4. Printing-Guard (neu, `printing_guard`): Der Tagespreis eines Produkts ist
   der Marktpreis des wertvollsten regulären Printings. Wechselt dieses
   Printing (z. B. Holo -> Reverse Holo), vergleicht ein naives Renditepaar
   zwei VERSCHIEDENE Güter und erzeugt eine künstliche Rendite. Solche Paare
   werden verworfen und in `diagnostics` gezählt.
5. Startniveau `base_level` am ersten Datentag; Verketten an eine
   Vorgeschichte über `start_level`.

Alle Parameter stehen in `IndexRules`; die Historie wird bei jedem Lauf
deterministisch neu gerechnet (kein persistenter Zwischenstand).
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import asdict, dataclass, field

BASE_LEVEL = 1000.0


@dataclass(frozen=True)
class IndexRules:
    size: int = 500
    carry_max_days: int = 70
    outlier_hi: float = 2.5
    outlier_lo: float = 0.4
    outlier_window: int = 14
    outlier_min_history: int = 5
    return_winsor: float = 0.01
    min_return_pairs: int = 100
    printing_guard: bool = True
    base_level: float = BASE_LEVEL
    label: str = "standard"

    def as_dict(self) -> dict:
        return asdict(self)


# Regelfassung, die die Artefakte vor der Konsolidierung erzeugt hat.
# Wird ausschließlich von den Golden-Master-Tests verwendet, um zu belegen,
# dass die neue Bibliothek die alte Berechnung bitgenau reproduziert.
LEGACY_RULES = IndexRules(min_return_pairs=20, printing_guard=False,
                          label="legacy-2026-07")


@dataclass
class Series:
    """Eine Produktreihe im Indexuniversum."""
    adj: list          # bereinigte Preise (cents) je Datumsindex, None = fehlt
    conf: list         # True = bestätigter Originalpreis
    raw: list          # Rohpreise (cents), None = fehlt
    variant: list = field(default_factory=list)   # Printing/sub_type je Tag

    def variant_at(self, di: int):
        return self.variant[di] if di < len(self.variant) else None


def adjust(raw: dict, dates: list, rules: IndexRules = IndexRules()):
    """Ausreißer-Guard + Carry-Forward. raw: {dateindex: cents}."""
    n = len(dates)
    adj = [None] * n
    conf = [False] * n
    hist: list = []
    dev_run = 0
    last_val = last_di = None
    date_objs = [dt.date.fromisoformat(d) for d in dates]
    for di in range(n):
        r = raw.get(di)
        if r is not None:
            suspicious = False
            if len(hist) >= rules.outlier_min_history:
                med = statistics.median(hist[-rules.outlier_window:])
                if r > med * rules.outlier_hi or r < med * rules.outlier_lo:
                    suspicious = dev_run < 1      # zweiter Tag bestätigt
            if suspicious:
                dev_run += 1
                med = statistics.median(hist[-rules.outlier_window:])
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
               (date_objs[di] - date_objs[last_di]).days <= rules.carry_max_days:
                adj[di] = last_val
                conf[di] = False
    return adj, conf


def build_universe(per_product: dict, dates: list, rules: IndexRules,
                   variants: dict | None = None) -> dict:
    """{pid: {di: cents}} -> {pid: Series}. variants: {pid: {di: sub_type}}."""
    n = len(dates)
    out = {}
    for pid, raw in per_product.items():
        a, c = adjust(raw, dates, rules)
        var = variants.get(pid, {}) if variants else {}
        out[pid] = Series(adj=a, conf=c,
                          raw=[raw.get(di) for di in range(n)],
                          variant=[var.get(di) for di in range(n)])
    return out


def _winsorized_mean(values: list, winsor: float) -> float:
    v = sorted(values)
    lo = v[int(len(v) * winsor)]
    hi = v[min(len(v) - 1, int(len(v) * (1 - winsor)))]
    return sum(min(max(x, lo), hi) for x in v) / len(v)


def daily_returns(universe: dict, members: list, di_prev: int, di: int,
                  rules: IndexRules) -> tuple[list, int]:
    """Rohe Renditepaare der Vortagsmitglieder. -> (renditen, verworfene_paare)."""
    rets, dropped = [], 0
    for pid in members:
        s = universe[pid]
        a, b = s.raw[di_prev], s.raw[di]
        if not a or not b:
            continue
        if rules.printing_guard:
            va, vb = s.variant_at(di_prev), s.variant_at(di)
            if va is not None and vb is not None and va != vb:
                dropped += 1
                continue
        rets.append(b / a - 1)
    return rets, dropped


def compute_index(name: str, dates: list, universe: dict, products: dict,
                  rules: IndexRules = IndexRules(),
                  start_level: float | None = None) -> dict | None:
    """Top-N-Kettenindex. Liefert das Ausgabedokument für Website/Newsletter."""
    n = len(dates)
    level = rules.base_level if start_level is None else start_level
    series: list = []
    prev_members = None
    prev_di = None
    members = None
    diag = {"variant_pairs_dropped": 0, "days_without_breadth": 0,
            "pairs_min": None, "pairs_max": None, "carried_share_last": None}

    for di in range(n):
        priced = {pid: s.adj[di] for pid, s in universe.items()
                  if s.adj[di] is not None}
        if not priced:
            continue
        top = sorted(priced.items(), key=lambda kv: (-kv[1], kv[0]))[:rules.size]
        members_today = [pid for pid, _ in top]

        if prev_members is not None:
            rets, dropped = daily_returns(universe, prev_members, prev_di, di, rules)
            diag["variant_pairs_dropped"] += dropped
            k = len(rets)
            diag["pairs_min"] = k if diag["pairs_min"] is None else min(diag["pairs_min"], k)
            diag["pairs_max"] = k if diag["pairs_max"] is None else max(diag["pairs_max"], k)
            if k >= rules.min_return_pairs:
                level *= (1 + _winsorized_mean(rets, rules.return_winsor))
            else:
                diag["days_without_breadth"] += 1

        basket = sum(c for _, c in top) / 100.0
        adv = dec = 0
        if prev_members is not None:
            for pid in members_today:
                s = universe[pid]
                if s.conf[di] and s.conf[prev_di] and s.adj[prev_di]:
                    if s.adj[di] > s.adj[prev_di]:
                        adv += 1
                    elif s.adj[di] < s.adj[prev_di]:
                        dec += 1
        series.append({"d": dates[di], "l": round(level, 2),
                       "b": round(basket), "a": adv, "e": dec})
        prev_members, prev_di, members = members_today, di, top

    if not series:
        return None

    last_di = dates.index(series[-1]["d"])
    prev_di_glob = dates.index(series[-2]["d"]) if len(series) > 1 else None
    member_set_prev = set()
    if prev_di_glob is not None:
        priced_prev = {pid: s.adj[prev_di_glob] for pid, s in universe.items()
                       if s.adj[prev_di_glob] is not None}
        member_set_prev = {pid for pid, _ in sorted(
            priced_prev.items(), key=lambda kv: (-kv[1], kv[0]))[:rules.size]}

    wk_di = None
    last_date = dt.date.fromisoformat(dates[last_di])
    for di in range(last_di, -1, -1):
        if (last_date - dt.date.fromisoformat(dates[di])).days >= 7:
            wk_di = di
            break

    rows, movers = [], []
    carried = 0
    for rank, (pid, cents) in enumerate(members, 1):
        s = universe[pid]
        p = products.get(pid, {})
        chg = None
        if prev_di_glob is not None and s.conf[last_di] and s.conf[prev_di_glob] \
                and s.adj[prev_di_glob]:
            chg = round((s.adj[last_di] / s.adj[prev_di_glob] - 1) * 100, 2)
        wchg = None
        if wk_di is not None and s.conf[last_di] and s.conf[wk_di] and s.adj[wk_di]:
            wchg = round((s.adj[last_di] / s.adj[wk_di] - 1) * 100, 2)
        car = 0 if s.conf[last_di] else 1
        carried += car
        row = {"id": pid, "r": rank, "n": p.get("name", "?"),
               "s": p.get("group_name", ""), "num": p.get("number"),
               "p": cents / 100.0, "chg": chg, "wchg": wchg,
               "car": car,
               "new": 1 if (member_set_prev and pid not in member_set_prev) else 0,
               "cat": p.get("sealed_cat"), "u": p.get("url")}
        rows.append(row)
        if chg is not None and chg != 0:
            movers.append(row)

    diag["carried_share_last"] = round(carried / max(len(rows), 1), 4)

    movers.sort(key=lambda r: r["chg"], reverse=True)
    gainers = movers[:6]
    losers = sorted(movers, key=lambda r: r["chg"])[:6]
    wk = [r for r in rows if r["wchg"] is not None and r["wchg"] != 0]
    wk_up = sorted(wk, key=lambda r: r["wchg"], reverse=True)[:5]
    wk_dn = sorted(wk, key=lambda r: r["wchg"])[:5]
    levels = [s["l"] for s in series]

    return {
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
        "rules": rules.as_dict(),
        "diagnostics": diag,
    }


# ------------------------------------------------------- gleichgewichtet (EW)
def ew_chain(dates: list, raw: dict, start_level: float = 100.0,
             winsor: float = 0.01, min_pairs: int = 50,
             eligible=None) -> list:
    """Gleichgewichteter Kettenindex über ALLE Reihen (Marktbreite statt Top-N).

    raw: {item_id: {dateindex: cents}}
    eligible: optionales Prädikat (item_id, dateindex) -> bool (z. B.
              Seasoning-/Mindestpreisfilter).
    """
    level = start_level
    out = []
    for di in range(len(dates)):
        if di == 0:
            out.append([dates[0], round(level, 2)])
            continue
        rets = []
        for iid, s in raw.items():
            a, b = s.get(di - 1), s.get(di)
            if a is None or b is None or a <= 0:
                continue
            if eligible is not None and not eligible(iid, di):
                continue
            rets.append(b / a - 1)
        if len(rets) >= min_pairs:
            level *= (1 + _winsorized_mean(rets, winsor))
        out.append([dates[di], round(level, 2)])
    return out


def monthly_topn_chain(hist: dict, upto_month: str, rules: IndexRules,
                       min_breadth: int = 50, start_month: str = "0000-00",
                       carry_months: int = 6,
                       min_pairs: int | None = None) -> tuple[list, float]:
    """Monatlicher Top-N-Kettenindex (Vorgeschichte aus Monatsdaten).

    hist: {name: [[JJJJ-MM, cents, volumen], ...]}
    min_pairs: Mindestbreite je Monatspaar. Bewusst getrennt von der
        Tagesregel: bei Monatsdaten ist die verfügbare Breite in frühen
        Perioden strukturell kleiner, eine Tagesschwelle würde die
        Vorgeschichte einfrieren statt sie zu berechnen.
    Liefert (serie, endniveau) zum Verketten mit dem Tagesindex.
    """
    if min_pairs is None:
        min_pairs = 20
    breadth: dict = {}
    for s in hist.values():
        for p in s:
            if p[0] < upto_month:
                breadth[p[0]] = breadth.get(p[0], 0) + 1
    months = sorted(m for m, cnt in breadth.items()
                    if cnt >= min_breadth and m >= start_month)
    if not months:
        return [], rules.base_level
    midx = {m: i for i, m in enumerate(months)}
    per_item = {}
    for name, s in hist.items():
        d = {midx[m]: cents for m, cents, _v in s if m in midx}
        if d:
            per_item[name] = d

    def mdiff(a: str, b: str) -> int:
        return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))

    adjusted = {}
    for name, d in per_item.items():
        arr = [None] * len(months)
        last_val = last_mi = None
        for mi in range(len(months)):
            if mi in d:
                arr[mi] = d[mi]
                last_val, last_mi = d[mi], mi
            elif last_val is not None and mdiff(months[last_mi], months[mi]) <= carry_months:
                arr[mi] = last_val
        adjusted[name] = arr

    level = rules.base_level
    series, prev_members, prev_mi = [], None, None
    for mi in range(len(months)):
        priced = {nm: arr[mi] for nm, arr in adjusted.items() if arr[mi] is not None}
        if not priced:
            continue
        top = sorted(priced.items(), key=lambda kv: (-kv[1], kv[0]))[:rules.size]
        members_today = [nm for nm, _ in top]
        if prev_members is not None:
            rets = []
            for nm in prev_members:
                a = per_item.get(nm, {}).get(prev_mi)
                b = per_item.get(nm, {}).get(mi)
                if a and b:
                    rets.append(b / a - 1)
            if len(rets) >= min_pairs:
                level *= (1 + _winsorized_mean(rets, rules.return_winsor))
        series.append([months[mi] + "-01", round(level, 2)])
        prev_members, prev_mi = members_today, mi
    return series, level
