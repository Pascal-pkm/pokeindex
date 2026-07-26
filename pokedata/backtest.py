# -*- coding: utf-8 -*-
"""Backtest der Screening-Signale – die fehlende Validierung.

Ein Score, der nie gegen die Zukunft geprüft wurde, ist eine Meinung. Dieses
Modul macht daraus eine überprüfbare Aussage:

  * Event-Study: Signal am Stichtag t -> Forward-Rendite über 30/90/180 Tage
  * Quintilanalyse: monoton steigende Renditen über die Score-Quintile sind das
    Qualitätskriterium (nicht der Mittelwert des besten Quintils allein)
  * Information Coefficient: Spearman-Rangkorrelation Score vs. Forward-Rendite
    je Stichtag, plus t-Statistik über alle Stichtage
  * Long-only-Strategie: Top-N kaufen, H Tage halten, Round-Trip-Gebühren
    abziehen -> das ist die Zahl, die zählt

Fallstricke, die bewusst adressiert werden:
  * Look-ahead: Scores werden ausschließlich aus Daten <= t berechnet.
  * Survivorship: Produkte ohne Preis am Ende des Horizonts gelten als
    "nicht realisierbar" und werden separat gezählt statt stillschweigend
    ausgeschlossen.
  * Überlappende Perioden: Stichtage sind konfigurierbar (Standard 30 Tage
    Abstand); überlappende Horizonte werden im Ergebnis vermerkt, weil sie
    die Signifikanz überschätzen.
  * Gebühren: Round-Trip über fees.py, sonst ist jede Bruttorendite Fiktion.
"""
from __future__ import annotations

import datetime as dt
import math

from . import fees as fee_mod
from . import screen as screen_mod


def _shift(day: str, days: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


def price_on_or_before(s: dict, day: str, max_gap: int = 14):
    """Preis am Tag oder letzter Preis innerhalb `max_gap` Tagen."""
    if day in s:
        return s[day]
    d = dt.date.fromisoformat(day)
    for back in range(1, max_gap + 1):
        k = (d - dt.timedelta(days=back)).isoformat()
        if k in s:
            return s[k]
    return None


def forward_return(s: dict, day: str, horizon: int, max_gap: int = 14):
    a = price_on_or_before(s, day, max_gap)
    b = price_on_or_before(s, _shift(day, horizon), max_gap)
    if not a or not b or a <= 0:
        return None
    return b / a - 1


def _rank(xs: list) -> list:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list, ys: list):
    if len(xs) < 5:
        return None
    rx, ry = _rank(xs), _rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def rebalance_dates(all_dates: list, step_days: int, horizon: int,
                    warmup_days: int) -> list:
    """Stichtage mit Vorlauf (für Scores) und vollem Forward-Fenster."""
    if not all_dates:
        return []
    first = dt.date.fromisoformat(all_dates[0]) + dt.timedelta(days=warmup_days)
    last = dt.date.fromisoformat(all_dates[-1]) - dt.timedelta(days=horizon)
    out, d = [], first
    while d <= last:
        iso = d.isoformat()
        # nächstgelegenen vorhandenen Datentag wählen
        cand = [x for x in all_dates if x >= iso]
        if cand:
            out.append(cand[0])
        d += dt.timedelta(days=step_days)
    return sorted(set(out))


# Vergleichbare Signale, alle aus EINEM Scoring-Durchlauf ableitbar.
# Vorzeichen: +1 = hoher Wert soll hohe Forward-Rendite bedeuten.
SIGNALS = {
    "potenzial": ("score", +1, "Günstigkeit + Stabilität (bisheriges Dashboard-Signal)"),
    "guenstigkeit": ("guenstigkeit", +1, "nur Günstigkeit (Mean-Reversion)"),
    "stabilitaet": ("stabilitaet", +1, "nur Stabilität (Konsolidierung)"),
    "momentum": ("trend_pa_pct", +1, "Trendstärke der letzten ~6 Monate"),
    "teuer": ("preis_usd", +1, "Preisniveau (Kontrolle: kaufen die Teuren besser?)"),
}


def event_study(panel: dict, products: dict, horizons=(30, 90, 180),
                step_days: int = 30, warmup_days: int = 365,
                quantiles: int = 5, w_cheap: float = 0.5,
                min_obs: int = 40, platform: str = "cardmarket.com",
                signals=("potenzial", "guenstigkeit", "stabilitaet",
                         "momentum")) -> dict:
    """Auswertung mehrerer Signale in einem Durchlauf.

    Der Vergleich ist der eigentliche Erkenntnisgewinn: ein einzelnes Signal
    ohne Alternative lässt nicht erkennen, ob ein negativer IC am Signal oder
    am Marktregime liegt. Läuft z. B. Momentum positiv, während Günstigkeit
    negativ läuft, ist das eine Aussage über den Markt – und ein Argument
    gegen das bisherige Screening-Design.
    """
    all_dates = sorted({d for s in panel.values() for d in s})
    max_h = max(horizons)
    dates = rebalance_dates(all_dates, step_days, max_h, warmup_days)
    fee_roundtrip = fee_mod.model_for(platform).total_fee_pct(100.0)

    per_date = []
    for as_of in dates:
        # Scores ausschließlich aus Daten <= as_of (kein Look-ahead)
        sub = {pid: {d: v for d, v in s.items() if d <= as_of}
               for pid, s in panel.items()}
        rows = screen_mod.score_universe({p: s for p, s in sub.items() if s},
                                         as_of, products, min_obs=min_obs,
                                         w_cheap=w_cheap)
        rows = [r for r in rows if r["investierbar"]]
        if len(rows) < quantiles * 5:
            continue
        entry = {"as_of": as_of, "n": len(rows), "signale": {}}
        fwd = {}
        for h in horizons:
            fwd[h] = {}
            for r in rows:
                fwd[h][r["product_id"]] = forward_return(
                    panel[r["product_id"]], as_of, h)
        for sig in signals:
            field, sign, _desc = SIGNALS[sig]
            per_h = {}
            for h in horizons:
                pairs = [(sign * (r.get(field) or 0), fwd[h][r["product_id"]])
                         for r in rows if fwd[h].get(r["product_id"]) is not None]
                missing = len(rows) - len(pairs)
                if len(pairs) < quantiles * 5:
                    continue
                pairs.sort(key=lambda x: x[0])
                k = len(pairs) // quantiles
                buckets = []
                for q in range(quantiles):
                    lo = q * k
                    hi = (q + 1) * k if q < quantiles - 1 else len(pairs)
                    seg = pairs[lo:hi]
                    buckets.append(round(100 * sum(p[1] for p in seg) / len(seg), 2))
                ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
                top = pairs[-k:]
                gross = sum(p[1] for p in top) / len(top)
                per_h[h] = {
                    "n_bewertet": len(pairs), "n_ohne_endpreis": missing,
                    "quintile_pct": buckets,
                    "spread_top_bottom_pp": round(buckets[-1] - buckets[0], 2),
                    "ic": round(ic, 3) if ic is not None else None,
                    "top_brutto_pct": round(gross * 100, 2),
                    "top_netto_pct": round((gross - fee_roundtrip) * 100, 2),
                    "markt_brutto_pct": round(
                        100 * sum(p[1] for p in pairs) / len(pairs), 2),
                }
            if per_h:
                entry["signale"][sig] = per_h
        if entry["signale"]:
            per_date.append(entry)

    agg = {}
    for sig in signals:
        agg[sig] = {"beschreibung": SIGNALS[sig][2], "horizonte": {}}
        for h in horizons:
            blocks = [d["signale"][sig][h] for d in per_date
                      if sig in d["signale"] and h in d["signale"][sig]]
            if not blocks:
                continue
            ics = [b["ic"] for b in blocks if b["ic"] is not None]
            spreads = [b["spread_top_bottom_pp"] for b in blocks]
            tops = [b["top_netto_pct"] for b in blocks]
            mkts = [b["markt_brutto_pct"] for b in blocks]
            quints = [b["quintile_pct"] for b in blocks]
            mean_ic = sum(ics) / len(ics) if ics else None
            sd_ic = (math.sqrt(sum((x - mean_ic) ** 2 for x in ics) / (len(ics) - 1))
                     if ics and len(ics) > 1 else None)
            t_ic = (mean_ic / (sd_ic / math.sqrt(len(ics)))
                    if mean_ic is not None and sd_ic and sd_ic > 0 else None)
            mean_q = [round(sum(q[i] for q in quints) / len(quints), 2)
                      for i in range(len(quints[0]))] if quints else None
            agg[sig]["horizonte"][h] = {
                "stichtage": len(blocks),
                "ic_mittel": round(mean_ic, 3) if mean_ic is not None else None,
                "ic_t_stat": round(t_ic, 2) if t_ic is not None else None,
                "ic_positiv_anteil_pct": (
                    round(100 * sum(1 for x in ics if x > 0) / len(ics), 1)
                    if ics else None),
                "quintile_mittel_pct": mean_q,
                "quintile_monoton": (bool(mean_q and all(
                    mean_q[i] <= mean_q[i + 1] + 1e-9
                    for i in range(len(mean_q) - 1))) if mean_q else None),
                "spread_mittel_pp": round(sum(spreads) / len(spreads), 2),
                "top_netto_mittel_pct": round(sum(tops) / len(tops), 2),
                "markt_mittel_pct": round(sum(mkts) / len(mkts), 2),
                "ueberschuss_netto_pp": round(sum(tops) / len(tops)
                                              - sum(mkts) / len(mkts), 2),
            }
    return {
        "parameter": {"horizonte": list(horizons), "schrittweite_tage": step_days,
                      "vorlauf_tage": warmup_days, "quantile": quantiles,
                      "gewicht_guenstigkeit": w_cheap,
                      "round_trip_gebuehr_pct": round(fee_roundtrip * 100, 2),
                      "gebuehrenmodell": platform,
                      "signale": list(signals)},
        "hinweise": [
            "Überlappende Halteperioden (Schrittweite < Horizont) überschätzen "
            "die Signifikanz; die IC-t-Statistik ist daher nur eine Indikation.",
            "Der Auswertungszeitraum umfasst nur ein Marktregime (starker "
            "Aufwärtsmarkt 2024-2026). Ergebnisse sind nicht auf fallende "
            "Märkte übertragbar.",
            "Preise sind Marktpreis-Schätzer, keine ausgeführten Trades; "
            "Liquiditäts- und Spread-Effekte fehlen über die Pauschalgebühr "
            "hinaus.",
        ],
        "aggregat": agg,
        "stichtage": per_date,
    }


def strategy_curve(panel: dict, products: dict, top_n: int = 20,
                   hold_days: int = 90, warmup_days: int = 365,
                   w_cheap: float = 0.5, platform: str = "cardmarket.com",
                   signal: str = "potenzial") -> dict:
    """Long-only-Strategie: alle `hold_days` Top-N kaufen, netto nach Gebühren.

    Vergleichsmaßstab ist der gleichgewichtete Markt über dieselbe Periode –
    eine positive Strategierendite in einem steigenden Markt ist kein Beleg
    für Signalqualität.
    """
    field, sign, _desc = SIGNALS[signal]
    all_dates = sorted({d for s in panel.values() for d in s})
    dates = rebalance_dates(all_dates, hold_days, hold_days, warmup_days)
    fee_roundtrip = fee_mod.model_for(platform).total_fee_pct(100.0)
    level_net = 100.0
    level_mkt = 100.0
    curve, curve_mkt, trades = [], [], []
    for as_of in dates:
        sub = {pid: {d: v for d, v in s.items() if d <= as_of}
               for pid, s in panel.items()}
        rows = screen_mod.score_universe({p: s for p, s in sub.items() if s},
                                         as_of, products, w_cheap=w_cheap)
        rows = [r for r in rows if r["investierbar"]]
        rows.sort(key=lambda r: -sign * (r.get(field) or 0))
        rows = rows[:top_n]
        rets, mkt = [], []
        for r in rows:
            fr = forward_return(panel[r["product_id"]], as_of, hold_days)
            if fr is not None:
                rets.append(fr)
        for _pid, s in panel.items():
            fr = forward_return(s, as_of, hold_days)
            if fr is not None:
                mkt.append(fr)
        if not rets or not mkt:
            continue
        r_net = sum(rets) / len(rets) - fee_roundtrip
        r_mkt = sum(mkt) / len(mkt)
        level_net *= (1 + r_net)
        level_mkt *= (1 + r_mkt)
        end = _shift(as_of, hold_days)
        curve.append([end, round(level_net, 2)])
        curve_mkt.append([end, round(level_mkt, 2)])
        trades.append({"as_of": as_of, "n": len(rets),
                       "rendite_netto_pct": round(r_net * 100, 2),
                       "markt_pct": round(r_mkt * 100, 2)})
    return {"strategie_netto": curve, "markt_gleichgewichtet": curve_mkt,
            "trades": trades,
            "parameter": {"signal": signal, "top_n": top_n,
                          "haltedauer_tage": hold_days,
                          "round_trip_gebuehr_pct": round(fee_roundtrip * 100, 2)},
            "ergebnis": {"strategie_netto_pct": round(level_net - 100, 2),
                         "markt_pct": round(level_mkt - 100, 2),
                         "ueberschuss_pp": round(level_net - level_mkt, 2)}}


def summarize(agg: dict, horizon: int = 90) -> dict:
    """Rangliste der Signale nach Überschussrendite (für Bericht/Newsletter)."""
    rows = []
    for sig, block in agg.items():
        h = block.get("horizonte", {}).get(horizon)
        if not h:
            continue
        rows.append({"signal": sig, "beschreibung": block["beschreibung"],
                     "ic": h["ic_mittel"], "t": h["ic_t_stat"],
                     "ueberschuss_pp": h["ueberschuss_netto_pp"],
                     "monoton": h["quintile_monoton"],
                     "stichtage": h["stichtage"]})
    rows.sort(key=lambda r: -(r["ueberschuss_pp"] if r["ueberschuss_pp"] is not None
                              else -999))
    # Ein Signal gilt nur als belastbar, wenn ALLE drei Bedingungen gelten:
    # positiver Überschuss NACH Gebühren, signifikant POSITIVER IC (t > 2) und
    # monotone Quintile. Ein positiver Überschuss bei negativem IC ist ein
    # Zufallsbefund im obersten Quintil, kein Zusammenhang.
    belastbar = [r for r in rows
                 if (r["ueberschuss_pp"] or 0) > 0
                 and (r["t"] or 0) > 2
                 and (r["ic"] or 0) > 0
                 and r["monoton"]]
    if belastbar:
        b = belastbar[0]
        verdict = (f"belastbares Signal: {b['signal']} "
                   f"(+{b['ueberschuss_pp']} pp netto, IC {b['ic']}, t={b['t']}, "
                   f"monotone Quintile)")
    else:
        best_ic = max(rows, key=lambda r: (r["ic"] or -9)) if rows else None
        verdict = ("kein Signal mit belastbarem Mehrwert nach Gebühren "
                   "(kein Kandidat erfüllt Überschuss > 0, IC > 0, t > 2 und "
                   "monotone Quintile gleichzeitig)")
        if best_ic and (best_ic["ic"] or 0) > 0 and (best_ic["t"] or 0) > 2:
            verdict += (f"; höchster signifikanter IC: {best_ic['signal']} "
                        f"({best_ic['ic']}, t={best_ic['t']}) – die "
                        f"Rangkorrelation ist positiv, die Netto-Überrendite "
                        f"des Top-Quintils aber nicht")
    return {"horizont": horizon, "rangliste": rows, "fazit": verdict,
            "kriterien": ("Überschuss netto > 0 pp UND IC > 0 UND t > 2 UND "
                          "monotone Quintile")}
