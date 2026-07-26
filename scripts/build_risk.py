# -*- coding: utf-8 -*-
"""Risiko- und Vergleichskennzahlen aller Anlageklassen.

Beantwortet die Fragen, die aus Preisreihen erst eine Anlageanalyse machen:
Wie volatil ist der Markt? Wie tief war der schlimmste Rückgang? Wie sieht die
risikoadjustierte Rendite aus? Und – für die Diversifikationsfrage
entscheidend – wie stark laufen Sammlermärkte mit Aktien, Gold und Bitcoin?

Ausgabe:
  site/data/risk.js       window.RISK = {kennzahlen, korrelationen, rollierend,
                                         vergleich}
  site/data/risk.json     identischer Inhalt für Auswertungen/Excel

Aufruf:  python scripts/build_risk.py [--rf 0.02] [--since 2024-02-08]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from common import CARD_INDEX, CS2_INDEX, SEALED_INDEX, SITE_DATA

from pokedata import METHOD_VERSION, risk
from pokedata.atomicio import read_js_var, write_js_var, write_json

IDX_FILES = {CARD_INDEX: "idx_SPK500.js", SEALED_INDEX: "idx_SPKS.js",
             CS2_INDEX: "idx_CS2.js"}
LABELS = {CARD_INDEX: "Karten (SPK500)", SEALED_INDEX: "Sealed (SPKS)",
          CS2_INDEX: "CS2-Skins (CS2500)", "CS2_EW": "CS2 gleichgewichtet",
          "SP500": "S&P 500", "DAX": "DAX", "NASDAQ100": "NASDAQ 100",
          "EUROSTOXX50": "EuroStoxx 50", "MSCIWORLD": "MSCI World",
          "GOLD": "Gold", "SILVER": "Silber", "BITCOIN": "Bitcoin"}
WINDOWS = {"30 Tage": 30, "90 Tage": 90, "1 Jahr": 365, "Gesamt": None}


def load_series() -> dict:
    out = {}
    for name, fn in IDX_FILES.items():
        path = os.path.join(SITE_DATA, fn)
        if not os.path.isfile(path):
            continue
        data = read_js_var(path)
        out[name] = [[d, v] for d, v in data["series"]]
        if name == CS2_INDEX and data.get("ew"):
            out["CS2_EW"] = [[d, v] for d, v in data["ew"]]
    mpath = os.path.join(SITE_DATA, "markets.js")
    if os.path.isfile(mpath):
        mk = read_js_var(mpath)
        for n, s in (mk.get("series") or {}).items():
            out[n] = [[d, v] for d, v in s]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rf", type=float, default=risk.DEFAULT_RF,
                    help="risikofreier Zins p. a. (Standard 0,02)")
    ap.add_argument("--since", default=None,
                    help="Vergleichsstart (Standard: erster gemeinsamer Tag)")
    args = ap.parse_args()

    series = load_series()
    if not series:
        print("Keine Indexreihen gefunden – zuerst build_indices.py ausführen.")
        return 1

    # ---- Kennzahlen je Reihe und Zeitfenster ----
    kennzahlen = {}
    for name, s in series.items():
        per_window = {}
        for label, days in WINDOWS.items():
            sub = risk.window(s, days) if days else s
            if len(sub) >= 3:
                per_window[label] = risk.metrics(sub, args.rf, LABELS.get(name, name))
        kennzahlen[name] = {"label": LABELS.get(name, name), "fenster": per_window}

    # ---- Korrelationen (Sammlermärkte vs. klassische Anlagen) ----
    collectibles = [n for n in (CARD_INDEX, SEALED_INDEX, CS2_INDEX, "CS2_EW")
                    if n in series]
    classic = [n for n in ("SP500", "NASDAQ100", "DAX", "EUROSTOXX50",
                           "MSCIWORLD", "GOLD", "SILVER", "BITCOIN")
               if n in series]
    corr = risk.correlation_matrix({n: series[n] for n in collectibles + classic})
    betas = {}
    for c in collectibles:
        betas[c] = {b: risk.beta(series[c], series[b]) for b in classic}

    # ---- Rollierende Kennzahlen ----
    rolling = {}
    for n in collectibles:
        rolling[n] = {
            "vola_90d": risk.rolling_volatility(series[n], 90, step=3),
            "korr_sp500_180d": (risk.rolling_correlation(series[n], series["SP500"],
                                                         180, step=7)
                                if "SP500" in series else []),
        }

    # ---- Einzelprodukt-Volatilität (Realitätsabgleich zum Index) ----
    einzel = {}
    try:
        from build_indices import load_series as load_card_series
        from common import read_products
        dates, per_product, _var = load_card_series()
        products = read_products()
        since = (dt.date.fromisoformat(dates[-1]) - dt.timedelta(days=365)).isoformat()
        for target, is_sealed in ((CARD_INDEX, 0), (SEALED_INDEX, 1)):
            panel = {pid: {dates[di]: c for di, c in s.items()}
                     for pid, s in per_product.items()
                     if products.get(pid, {}).get("is_sealed") == is_sealed}
            einzel[target] = risk.single_asset_vol_distribution(panel, since)
    except Exception as exc:                              # noqa: BLE001
        print(f"  Einzelprodukt-Volatilität übersprungen: {exc}")

    # ---- Normierter Vergleich (Basis 100) ----
    start = args.since
    if not start:
        firsts = [s[0][0] for n, s in series.items() if n in collectibles and s]
        start = max(firsts) if firsts else None
    vergleich = {}
    for n in collectibles + classic:
        reb = risk.rebase(series[n], 100.0, start)
        if reb:
            vergleich[n] = reb
    perf = {n: round(v[-1][1] - 100, 2) for n, v in vergleich.items()}

    out = {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "method_version": METHOD_VERSION,
        "rf_pa": args.rf,
        "labels": LABELS,
        "kennzahlen": kennzahlen,
        "korrelation": corr,
        "beta_vs_klassisch": betas,
        "rollierend": rolling,
        "einzelprodukt_vola": einzel,
        "vergleich": {"start": start, "series": vergleich, "performance_pct": perf},
        "methodik": {
            "renditen": "einfache Renditen zwischen aufeinanderfolgenden Punkten",
            "annualisierung": "365 Kalendertage",
            "vola": ("Stichproben-Standardabweichung (ddof=1) der mit "
                     "1/sqrt(Abstand in Tagen) skalierten Renditen, annualisiert – "
                     "notwendig, weil die CS2-Reihe Monats- und Tagespunkte mischt"),
            "rendite_pa": "geometrisch (CAGR), sofern der Zeitraum >= 3 Monate ist",
            "sharpe": "(CAGR - rf) / Vola p.a.",
            "korrelation": "Pearson auf gemeinsamen Tagen (Schnittmenge)",
            "warnung_glaettung": (
                "WICHTIG: Die Indexvolatilität ist strukturell zu niedrig. Ein "
                "gleichgewichteter Index aus 500 Positionen mittelt "
                "idiosynkratische Schwankungen weg, Carry-Forward glättet "
                "zusätzlich. Sharpe Ratios über 3 sind ein Artefakt dieser "
                "Glättung, keine Anlageeigenschaft. Für die Risikoeinschätzung "
                "einzelner Käufe ist `einzelprodukt_vola` die richtige Größe."),
            "hinweis_preisart": (
                "Preise sind Marktpreis-Schätzer (TCGplayer) bzw. "
                "Angebotsmediane (Skinport), keine realisierten "
                "Transaktionspreise; Gebühren und Spread sind nicht enthalten "
                "(siehe pokedata/fees.py)."),
        },
    }
    write_js_var(os.path.join(SITE_DATA, "risk.js"), "RISK", out)
    write_json(os.path.join(SITE_DATA, "risk.json"), out)

    print(f"Risiko-Kennzahlen für {len(kennzahlen)} Reihen geschrieben "
          f"(Vergleichsstart {start}).")
    for n in collectibles:
        g = kennzahlen[n]["fenster"].get("Gesamt") or {}
        print(f"  {LABELS.get(n, n):24s} Rendite {g.get('rendite_gesamt_pct')}% "
              f"| Vola {g.get('vola_pa_pct')}% | MaxDD {g.get('max_drawdown_pct')}% "
              f"| Sharpe {g.get('sharpe')}")
    for name, dist in einzel.items():
        if dist:
            print(f"  Einzelprodukt-Vola {LABELS.get(name, name)}: Median "
                  f"{dist['median_pa_pct']}% p.a. (Index-Vola ist durch "
                  f"Mittelung deutlich niedriger, n={dist['n']})")
    if "SP500" in series:
        print("  Korrelation zu S&P 500:")
        names = corr["names"]
        i_sp = names.index("SP500")
        for c in collectibles:
            print(f"    {LABELS.get(c, c):24s} {corr['matrix'][names.index(c)][i_sp]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
