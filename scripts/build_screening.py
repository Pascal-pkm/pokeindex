# -*- coding: utf-8 -*-
"""Potenzial-Screening auf den tagesaktuellen Daten – inklusive Backtest.

Zwei Dinge, die vorher fehlten:
  1. Das Screening lief nur im Sealed-Dashboard auf einem Datenstand, der
     Wochen alt war. Hier läuft es auf der täglich fortgeschriebenen Reihe.
  2. Es war nie gegen die Zukunft geprüft. `--backtest` liefert Event-Study,
     Quintilanalyse, Information Coefficient und eine Netto-Strategiekurve
     nach Gebühren. Ohne diese Zahlen ist ein Score eine Meinung.

Ausgabe:
  site/data/screen.js      window.SCREEN = {sealed, karten, backtest?}
  site/data/screen.json    identischer Inhalt

Aufruf:
  python scripts/build_screening.py                     # nur Screening
  python scripts/build_screening.py --backtest          # + Validierung (dauert)
  python scripts/build_screening.py --backtest --universe karten
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

from build_indices import load_series
from common import SITE_DATA, read_products

from pokedata import METHOD_VERSION, backtest, fees, screen
from pokedata.atomicio import write_js_var, write_json


def panels(dates, per_product, products):
    """(sealed_panel, karten_panel) als {pid: {datum: cents}}."""
    sealed, karten = {}, {}
    for pid, s in per_product.items():
        p = products.get(pid)
        if not p:
            continue
        target = karten if p["is_sealed"] == 0 else sealed
        target[pid] = {dates[di]: c for di, c in s.items()}
    return sealed, karten


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--universe", choices=["sealed", "karten", "beide"],
                    default="sealed", help="Universum für den Backtest")
    ap.add_argument("--w-cheap", type=float, default=0.5,
                    help="Gewicht der Günstigkeit im Gesamtscore")
    ap.add_argument("--top", type=int, default=300,
                    help="Anzahl ausgegebener Kandidaten je Universum")
    ap.add_argument("--platform", default="cardmarket.com",
                    help="Gebührenmodell für Netto-Renditen")
    args = ap.parse_args()

    products = read_products()
    dates, per_product, _var = load_series()
    if not dates:
        print("Keine Tagesdaten – zuerst fetch_prices.py ausführen.")
        return 1
    sealed, karten = panels(dates, per_product, products)
    as_of = dates[-1]
    print(f"Screening zum {as_of}: {len(sealed)} Sealed, {len(karten)} Karten")

    out = {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "method_version": METHOD_VERSION,
        "as_of": as_of,
        "parameter": {"gewicht_guenstigkeit": args.w_cheap,
                      "fenster_tage": screen.WINDOW_DAYS,
                      "band_pct": screen.BAND_PCT,
                      "min_beobachtungen": screen.MIN_OBS},
        "gebuehren": fees.model_for(args.platform).as_dict(),
        "methodik": {
            "guenstigkeit": ("Mittel der Perzentilränge von: niedrige Position "
                             "in der eigenen Preisspanne, Abschlag zum "
                             "Allzeithoch, Abstand unter dem Mittelwert"),
            "stabilitaet": ("Mittel der Perzentilränge von: niedrige "
                            "annualisierte Volatilität, lange Konsolidierung "
                            "im ±10-%-Band, flacher Trend, niedriger "
                            "Variationskoeffizient"),
            "hinweis": ("Long-only-Screening auf Akkumulationsniveaus, kein "
                        "Momentum-Signal. Ein weiterhin fallender Preis wird "
                        "als Risiko geflaggt, nicht als Kaufsignal. Keine "
                        "Anlageberatung."),
        },
    }

    for label, panel in (("sealed", sealed), ("karten", karten)):
        t0 = time.time()
        rows = screen.score_universe(panel, as_of, products, w_cheap=args.w_cheap)
        out[label] = {"n_bewertet": len(rows), "top": rows[:args.top]}
        inv = [r for r in rows if r["investierbar"]]
        print(f"  {label}: {len(rows)} bewertet, {len(inv)} investierbar "
              f"({time.time() - t0:.1f}s)")
        for r in inv[:5]:
            print(f"    {r['score']:5.1f}  {r['signal']:18s} "
                  f"{r['name'][:48]:48s} {r['preis_usd']:>9,.2f} USD")

    if args.backtest:
        targets = {"sealed": sealed, "karten": karten}
        if args.universe != "beide":
            targets = {args.universe: targets[args.universe]}
        out["backtest"] = {}
        for label, panel in targets.items():
            print(f"\nBacktest {label} – das dauert einige Minuten ...")
            t0 = time.time()
            es = backtest.event_study(panel, products, horizons=(30, 90, 180),
                                      step_days=30, warmup_days=365,
                                      w_cheap=args.w_cheap,
                                      platform=args.platform)
            st = backtest.strategy_curve(panel, products, top_n=20,
                                         hold_days=90, warmup_days=365,
                                         w_cheap=args.w_cheap,
                                         platform=args.platform)
            summary = backtest.summarize(es["aggregat"], horizon=90)
            out["backtest"][label] = {"event_study": es, "strategie": st,
                                      "fazit_90d": summary}
            print(f"  fertig in {time.time() - t0:.0f}s")
            print(f"  {'Signal':14s} {'IC':>7s} {'t':>7s} "
                  f"{'Überschuss netto':>18s}  monoton")
            for r in summary["rangliste"]:
                print(f"  {r['signal']:14s} {str(r['ic']):>7s} {str(r['t']):>7s} "
                      f"{str(r['ueberschuss_pp']) + ' pp':>18s}  {r['monoton']}")
            print(f"  Fazit (90 Tage): {summary['fazit']}")
            e = st["ergebnis"]
            print(f"  Strategie {st['parameter']['signal']} (Top "
                  f"{st['parameter']['top_n']}, {st['parameter']['haltedauer_tage']} "
                  f"Tage, netto): {e['strategie_netto_pct']} % vs. Markt "
                  f"{e['markt_pct']} % -> {e['ueberschuss_pp']} pp")

    write_js_var(os.path.join(SITE_DATA, "screen.js"), "SCREEN", out)
    write_json(os.path.join(SITE_DATA, "screen.json"), out)
    print(f"\nGeschrieben: {os.path.join(SITE_DATA, 'screen.js')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
