# -*- coding: utf-8 -*-
"""Risiko- und Vergleichskennzahlen für Indexreihen.

Das Projekt hatte reichlich Preisdaten, aber keine einzige Risikokennzahl auf
Indexebene – für eine Anlage- oder Masterarbeitsanalyse ist genau das der
Kern: Rendite ohne Volatilität, Drawdown und Korrelation zu klassischen
Anlagen ist keine Aussage.

Bewusst ohne numpy/pandas implementiert, damit die tägliche GitHub-Action
leichtgewichtig bleibt (die Website-Pipeline installiert nur requests, py7zr,
brotli, matplotlib).

Konventionen
------------
* Renditen: einfache Tagesrenditen auf Kalendertagsbasis der Indexreihe.
* Annualisierung: 365 Tage (die Reihen sind kalendertäglich, nicht
  börsentäglich – 252 wäre hier falsch).
* Volatilität: Stichproben-Standardabweichung (ddof=1).
* Sharpe: (Rendite p.a. - risikofreier Zins) / Volatilität p.a.
* Sortino: nur Abwärtsabweichungen im Nenner.
* Max Drawdown: größter relativer Rückgang vom laufenden Höchststand.
* Korrelation: Pearson auf gemeinsamen Tagen (Schnittmenge der Datumswerte).
"""
from __future__ import annotations

import datetime as dt
import math

PERIODS_PER_YEAR = 365.0
DEFAULT_RF = 0.02          # 2 % p. a. risikofrei (Geldmarkt EUR, Stand 2026)


def to_map(series) -> dict:
    """[[datum, level], ...] -> {datum: level}"""
    return {d: float(v) for d, v in series if v is not None}


def returns_with_gap(series) -> list:
    """[(datum, rendite, tage_seit_vorpunkt)]."""
    out = []
    prev = None
    for d, v in series:
        v = float(v)
        if prev is not None and prev[1] > 0:
            days = (dt.date.fromisoformat(d) - dt.date.fromisoformat(prev[0])).days
            if days > 0:
                out.append((d, v / prev[1] - 1, days))
        prev = (d, v)
    return out


def returns(series) -> list:
    """[(datum, rendite)] aus aufeinanderfolgenden Punkten."""
    return [(d, r) for d, r, _g in returns_with_gap(series)]


def scaled_returns(series) -> list:
    """Renditen auf Tagesbasis skaliert: r / sqrt(tage).

    Notwendig, weil verkettete Reihen gemischte Frequenzen enthalten (die
    CS2-Historie besteht bis 2026 aus MONATS-, danach aus TAGESpunkten). Wird
    eine Monatsrendite mit sqrt(365) annualisiert, entsteht eine dreistellige
    Scheinvolatilität – genau dieser Fehler steckte in der ersten Fassung.
    """
    return [(d, r / math.sqrt(g)) for d, r, g in returns_with_gap(series)]


def spacing(series) -> dict:
    """Diagnose der Punktabstände (erkennt gemischte Frequenzen)."""
    gaps = [g for _d, _r, g in returns_with_gap(series)]
    if not gaps:
        return {}
    gs = sorted(gaps)
    med = gs[len(gs) // 2]
    return {"median_tage": med, "min_tage": gs[0], "max_tage": gs[-1],
            "gemischte_frequenz": bool(gs[-1] >= 3 * max(med, 1))}


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _stdev(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def max_drawdown(series):
    """(max_drawdown_pct, peak_datum, tal_datum)."""
    peak = None
    peak_d = None
    worst = 0.0
    worst_peak = worst_trough = None
    for d, v in series:
        v = float(v)
        if peak is None or v > peak:
            peak, peak_d = v, d
        if peak and peak > 0:
            dd = v / peak - 1
            if dd < worst:
                worst, worst_peak, worst_trough = dd, peak_d, d
    if worst < 0:
        return round(worst * 100, 2), worst_peak, worst_trough
    return 0.0, None, None


def cagr(series):
    if len(series) < 2:
        return None
    d0, v0 = series[0][0], float(series[0][1])
    d1, v1 = series[-1][0], float(series[-1][1])
    days = (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days
    if days <= 0 or v0 <= 0:
        return None
    years = days / PERIODS_PER_YEAR
    if years < 0.25:                     # zu kurz für eine sinnvolle Jahresrate
        return None
    return round(((v1 / v0) ** (1 / years) - 1) * 100, 2)


def window(series, days: int):
    """Teilreihe der letzten `days` Kalendertage."""
    if not series:
        return []
    last = dt.date.fromisoformat(series[-1][0])
    cut = (last - dt.timedelta(days=days)).isoformat()
    return [p for p in series if p[0] >= cut]


def metrics(series, rf: float = DEFAULT_RF, label: str = "") -> dict:
    """Kennzahlenblock für eine Indexreihe.

    Volatilität wird aus abstandsskalierten Renditen berechnet (siehe
    `scaled_returns`), die Jahresrendite als geometrische Rate (CAGR), sofern
    der Zeitraum dafür lang genug ist. Sharpe/Sortino nutzen konsistent diese
    beiden Größen.
    """
    series = [(d, float(v)) for d, v in series if v is not None]
    if len(series) < 3:
        return {"label": label, "n": len(series)}
    raw_rets = [r for _d, r in returns(series)]
    sc = [r for _d, r in scaled_returns(series)]
    vol_d = _stdev(sc)
    vol_ann = vol_d * math.sqrt(PERIODS_PER_YEAR) if vol_d else None
    downside = [r for r in sc if r < 0]
    dvol = _stdev(downside)
    dvol_ann = dvol * math.sqrt(PERIODS_PER_YEAR) if dvol else None
    dd, peak_d, trough_d = max_drawdown(series)
    growth = cagr(series)
    mu_ann = (growth / 100.0 if growth is not None
              else (_mean(raw_rets) * PERIODS_PER_YEAR if raw_rets else None))
    sharpe = sortino = None
    if vol_ann and mu_ann is not None and vol_ann > 0:
        sharpe = round((mu_ann - rf) / vol_ann, 3)
    if dvol_ann and mu_ann is not None and dvol_ann > 0:
        sortino = round((mu_ann - rf) / dvol_ann, 3)
    return {
        "label": label,
        "n": len(series),
        "von": series[0][0], "bis": series[-1][0],
        "level": round(series[-1][1], 2),
        "rendite_gesamt_pct": round((series[-1][1] / series[0][1] - 1) * 100, 2),
        "cagr_pct": growth,
        "rendite_pa_pct": round(mu_ann * 100, 2) if mu_ann is not None else None,
        "vola_pa_pct": round(vol_ann * 100, 2) if vol_ann else None,
        "downside_vola_pa_pct": round(dvol_ann * 100, 2) if dvol_ann else None,
        "sharpe": sharpe, "sortino": sortino,
        "max_drawdown_pct": dd, "dd_peak": peak_d, "dd_trough": trough_d,
        "positive_tage_pct": (round(100 * sum(1 for r in raw_rets if r > 0)
                                    / len(raw_rets), 1) if raw_rets else None),
        "abstaende": spacing(series),
        "rf_pa": rf,
    }


def correlation(a, b):
    """(Pearson-Korrelation der Tagesrenditen, Anzahl gemeinsamer Tage)."""
    ra = dict(returns([(d, float(v)) for d, v in a]))
    rb = dict(returns([(d, float(v)) for d, v in b]))
    common = sorted(set(ra) & set(rb))
    if len(common) < 10:
        return None, len(common)
    xs = [ra[d] for d in common]
    ys = [rb[d] for d in common]
    mx, my = _mean(xs), _mean(ys)
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None, len(common)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(cov / (dx * dy), 3), len(common)


def correlation_matrix(series_by_name: dict) -> dict:
    names = sorted(series_by_name)
    out = {"names": names, "matrix": [], "overlap": []}
    for a in names:
        row, orow = [], []
        for b in names:
            if a == b:
                row.append(1.0)
                orow.append(len(series_by_name[a]))
                continue
            c, n = correlation(series_by_name[a], series_by_name[b])
            row.append(c)
            orow.append(n)
        out["matrix"].append(row)
        out["overlap"].append(orow)
    return out


def beta(asset, benchmark):
    """Beta der Anlage gegen die Benchmark (gemeinsame Tage)."""
    ra = dict(returns([(d, float(v)) for d, v in asset]))
    rb = dict(returns([(d, float(v)) for d, v in benchmark]))
    common = sorted(set(ra) & set(rb))
    if len(common) < 10:
        return None
    xs = [rb[d] for d in common]
    ys = [ra[d] for d in common]
    mx, my = _mean(xs), _mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(cov / var, 3)


def single_asset_vol_distribution(panel: dict, since: str | None = None,
                                  min_obs: int = 60) -> dict:
    """Verteilung der EINZELprodukt-Volatilitäten (Median, Quartile).

    Warum das gebraucht wird: Ein gleichgewichteter Index aus 500 Positionen
    mittelt idiosynkratische Schwankungen fast vollständig weg – seine
    gemessene Volatilität (bei SPKS unter 3 % p. a.) beschreibt nicht das
    Risiko, das ein Sammler mit wenigen Positionen tatsächlich trägt.
    Diese Verteilung liefert die realistische Vergleichsgröße.

    panel: {product_id: {datum: cents}}
    """
    vols = []
    for _pid, s in panel.items():
        pts = sorted((d, v) for d, v in s.items() if (not since or d >= since))
        if len(pts) < min_obs:
            continue
        sc = [r for _d, r in scaled_returns([(d, float(v)) for d, v in pts])]
        sd = _stdev(sc)
        if sd:
            vols.append(sd * math.sqrt(PERIODS_PER_YEAR) * 100)
    if not vols:
        return {}
    vols.sort()

    def q(p):
        return round(vols[min(len(vols) - 1, int(len(vols) * p))], 2)

    return {"n": len(vols), "median_pa_pct": q(0.5), "p25_pa_pct": q(0.25),
            "p75_pa_pct": q(0.75), "p90_pa_pct": q(0.90),
            "mittel_pa_pct": round(sum(vols) / len(vols), 2)}


def rolling_volatility(series, win_days: int = 90, step: int = 1) -> list:
    """[[datum, vola_pa_pct]] – rollierende annualisierte Volatilität."""
    pts = [(d, float(v)) for d, v in series if v is not None]
    rets = scaled_returns(pts)
    out = []
    for i in range(0, len(rets), step):
        d = rets[i][0]
        cut = (dt.date.fromisoformat(d) - dt.timedelta(days=win_days)).isoformat()
        wnd = [r for dd, r in rets[:i + 1] if dd >= cut]
        if len(wnd) >= max(10, win_days // 3):
            s = _stdev(wnd)
            if s:
                out.append([d, round(s * math.sqrt(PERIODS_PER_YEAR) * 100, 2)])
    return out


def rolling_correlation(a, b, win_days: int = 180, step: int = 7) -> list:
    """[[datum, korrelation]] – rollierende Korrelation der Tagesrenditen."""
    ra = dict(returns([(d, float(v)) for d, v in a]))
    rb = dict(returns([(d, float(v)) for d, v in b]))
    common = sorted(set(ra) & set(rb))
    out = []
    for i in range(0, len(common), step):
        d = common[i]
        cut = (dt.date.fromisoformat(d) - dt.timedelta(days=win_days)).isoformat()
        wnd = [x for x in common[:i + 1] if x >= cut]
        if len(wnd) < 20:
            continue
        xs = [ra[x] for x in wnd]
        ys = [rb[x] for x in wnd]
        mx, my = _mean(xs), _mean(ys)
        dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        dy = math.sqrt(sum((y - my) ** 2 for y in ys))
        if dx and dy:
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            out.append([d, round(cov / (dx * dy), 3)])
    return out


def rebase(series, base: float = 100.0, start: str | None = None) -> list:
    """Reihe auf `base` normieren (für Vergleichscharts)."""
    pts = [(d, float(v)) for d, v in series if v is not None]
    if start:
        pts = [p for p in pts if p[0] >= start]
    if not pts or pts[0][1] <= 0:
        return []
    f = base / pts[0][1]
    return [[d, round(v * f, 2)] for d, v in pts]
