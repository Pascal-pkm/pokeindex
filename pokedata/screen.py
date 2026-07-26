# -*- coding: utf-8 -*-
"""Potenzial-Screening auf den täglichen Preisdaten (Long-only).

Das Screening existierte nur im Sealed-Dashboard – auf Daten, die inzwischen
Wochen alt sind, und ohne jede Validierung. Diese Fassung arbeitet auf den
tagesaktuellen Reihen der Website-Pipeline, ist ohne pandas lauffähig und wird
von `backtest.py` gegen die Zukunft geprüft.

Leitidee (unverändert, weil ökonomisch sinnvoll): ein Sealed-Produkt ist als
langfristiger Kauf tendenziell attraktiv, wenn es
  (a) relativ zur eigenen Historie GÜNSTIG ist  und/oder
  (b) seit längerer Zeit auf STABILEM Niveau konsolidiert.
Beide Teilaspekte werden als Perzentil-Rang im Querschnitt gemessen und
gemittelt – dadurch ist der Score selbstkalibrierend und über Zeitpunkte
vergleichbar.

Neu gegenüber der alten Fassung:
  * berechnet auf beliebigem Stichtag (Voraussetzung für Backtests)
  * Momentum-Risikoflag getrennt ausgewiesen statt in den Score gemischt
  * Liquiditätsproxy (Anteil bestätigter Preistage) als Filter
"""
from __future__ import annotations

import datetime as dt
import math

WINDOW_DAYS = 365          # Beobachtungsfenster für Niveau-Kennzahlen
VOL_WINDOW_DAYS = 180      # Fenster für Volatilität/Trend
MIN_OBS = 40               # Mindestanzahl Preistage im Fenster
BAND_PCT = 0.10            # Konsolidierungsband ±10 %


def _pct_rank(values: dict) -> dict:
    """Werte -> Perzentilrang 0..100 (höher = größerer Wert)."""
    items = [(k, v) for k, v in values.items() if v is not None]
    if not items:
        return {}
    items.sort(key=lambda kv: kv[1])
    n = len(items)
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        rank = (i + j) / 2.0
        pct = 100.0 * rank / max(n - 1, 1)
        for k, _v in items[i:j + 1]:
            out[k] = round(pct, 2)
        i = j + 1
    return out


def _stdev(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _slope(ys):
    """OLS-Steigung von log(preis) gegen den Index (je Periode)."""
    n = len(ys)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def series_features(days: list, cents: list, band_pct: float = BAND_PCT) -> dict | None:
    """Roh-Kennzahlen einer Preisreihe (aufsteigend sortiert)."""
    if len(cents) < 3:
        return None
    last = cents[-1]
    if last <= 0:
        return None
    hi, lo = max(cents), min(cents)
    mean = sum(cents) / len(cents)
    span = hi - lo
    logs = [math.log(c) for c in cents if c > 0]
    rets = [logs[i] - logs[i - 1] for i in range(1, len(logs))]
    vol = _stdev(rets[-VOL_WINDOW_DAYS:]) if len(rets) >= 3 else None
    vol_ann = vol * math.sqrt(365) if vol else None
    win = logs[-VOL_WINDOW_DAYS:] if len(logs) > VOL_WINDOW_DAYS else logs
    trend_ann = _slope(win) * 365
    cw = cents[-VOL_WINDOW_DAYS:] if len(cents) > VOL_WINDOW_DAYS else cents
    cv = (_stdev(cw) / (sum(cw) / len(cw))) if len(cw) >= 2 and sum(cw) > 0 else None
    # Drawdown
    peak = cents[0]
    max_dd = 0.0
    for c in cents:
        peak = max(peak, c)
        max_dd = min(max_dd, c / peak - 1)
    # Konsolidierungsdauer: Perioden am Ende innerhalb ±band um das aktuelle Niveau
    cons = 0
    for c in reversed(cents):
        if abs(c / last - 1) <= band_pct:
            cons += 1
        else:
            break
    return {
        "last": last, "ath": hi, "atl": lo, "mean": mean,
        "n_obs": len(cents),
        "pct_in_range": (last - lo) / span if span > 0 else 0.5,
        "discount_ath": 1 - last / hi if hi > 0 else 0.0,
        "below_mean": max(0.0, 1 - last / mean) if mean > 0 else 0.0,
        "vol_ann": vol_ann,
        "trend_ann": trend_ann,
        "cv": cv,
        "max_dd": max_dd,
        "consolidation_days": cons,
        "consolidation_share": cons / len(cents),
    }


def score_universe(panel: dict, as_of: str, products: dict | None = None,
                   window_days: int = WINDOW_DAYS, min_obs: int = MIN_OBS,
                   w_cheap: float = 0.5, band_pct: float = BAND_PCT) -> list:
    """Screening zum Stichtag.

    panel: {product_id: {datum: cents}}
    Rückgabe: Liste von Dicts mit Teil- und Gesamtscore, sortiert absteigend.
    """
    products = products or {}
    cut = (dt.date.fromisoformat(as_of) - dt.timedelta(days=window_days)).isoformat()
    feats = {}
    for pid, s in panel.items():
        days = [d for d in sorted(s) if cut <= d <= as_of]
        if len(days) < min_obs:
            continue
        f = series_features(days, [s[d] for d in days], band_pct)
        if f:
            feats[pid] = f
    if not feats:
        return []

    # Günstigkeit: niedriges Niveau in der eigenen Historie
    r_range = _pct_rank({k: -f["pct_in_range"] for k, f in feats.items()})
    r_disc = _pct_rank({k: f["discount_ath"] for k, f in feats.items()})
    r_below = _pct_rank({k: f["below_mean"] for k, f in feats.items()})
    # Stabilität: geringe Schwankung, lange Konsolidierung, flacher Trend
    r_vol = _pct_rank({k: (-f["vol_ann"] if f["vol_ann"] is not None else None)
                       for k, f in feats.items()})
    r_cons = _pct_rank({k: f["consolidation_share"] for k, f in feats.items()})
    r_flat = _pct_rank({k: -abs(f["trend_ann"]) for k, f in feats.items()})
    r_cv = _pct_rank({k: (-f["cv"] if f["cv"] is not None else None)
                      for k, f in feats.items()})

    out = []
    for pid, f in feats.items():
        cheap_parts = [r_range.get(pid), r_disc.get(pid), r_below.get(pid)]
        stab_parts = [r_vol.get(pid), r_cons.get(pid), r_flat.get(pid), r_cv.get(pid)]
        cheap = [x for x in cheap_parts if x is not None]
        stab = [x for x in stab_parts if x is not None]
        if not cheap or not stab:
            continue
        cheap_s = sum(cheap) / len(cheap)
        stab_s = sum(stab) / len(stab)
        score = w_cheap * cheap_s + (1 - w_cheap) * stab_s

        flags = []
        if f["trend_ann"] < -0.15:
            flags.append("Abwärtstrend")
        if f["trend_ann"] > 0.35:
            flags.append("bereits gelaufen")
        if f["vol_ann"] and f["vol_ann"] > 0.6:
            flags.append("hohe Volatilität")
        if f["consolidation_share"] > 0.95 and (f["cv"] or 0) < 0.01:
            flags.append("statischer Preis / illiquide")
        if f["n_obs"] < min_obs * 2:
            flags.append("dünne Historie")

        if cheap_s >= 66 and stab_s >= 66:
            signal = "Günstig & stabil"
        elif stab_s >= 66:
            signal = "Stabile Basis"
        elif cheap_s >= 66:
            signal = "Nahe Tief"
        elif score >= 50:
            signal = "Solide"
        else:
            signal = "Neutral"

        p = products.get(pid, {})
        out.append({
            "product_id": pid,
            "name": p.get("name", str(pid)),
            "set": p.get("group_name", ""),
            "kategorie": p.get("sealed_cat"),
            "is_sealed": p.get("is_sealed"),
            "preis_usd": round(f["last"] / 100.0, 2),
            "guenstigkeit": round(cheap_s, 1),
            "stabilitaet": round(stab_s, 1),
            "score": round(score, 1),
            "signal": signal,
            "vola_pa_pct": round(f["vol_ann"] * 100, 1) if f["vol_ann"] else None,
            "trend_pa_pct": round(f["trend_ann"] * 100, 1),
            "abschlag_ath_pct": round(f["discount_ath"] * 100, 1),
            "konsolidierung_tage": f["consolidation_days"],
            "max_dd_pct": round(f["max_dd"] * 100, 1),
            "n_obs": f["n_obs"],
            "risiken": flags,
            "investierbar": 0 if ("statischer Preis / illiquide" in flags
                                  or "dünne Historie" in flags) else 1,
        })
    out.sort(key=lambda r: -r["score"])
    return out
