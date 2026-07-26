# -*- coding: utf-8 -*-
"""Portfolio-Bewertung aus dem echten Order Book – LOKAL, nicht öffentlich.

Wichtig: Die Ausgaben landen bewusst NICHT in site/ (GitHub Pages ist
öffentlich und das Repository ebenso). Eigene Kaufpreise, Mengen und Plattformen
sind private Daten. Geschrieben wird in den Projektordner eine Ebene über dem
Repository:

  Portfolio_Bericht.html      lesbarer Bericht mit Charts
  Portfolio_Analyse.xlsx      Arbeitsmappe mit allen Zwischenschritten
  portfolio_map.csv           Zuordnung deutscher Artikel -> englische Produkte
                              (EDITIERBAR – Korrekturen bleiben erhalten)
  portfolio_prices_manual.csv optionale echte Cardmarket-Preise (EUR)
  portfolio.json              Rohergebnis für weitere Auswertungen

Bewertungshierarchie: manuelle EUR-Beobachtung > TCGplayer-EN-Proxy (USD->EUR,
skaliert) > nicht bewertet. Der Proxy-Anteil wird immer ausgewiesen.

Aufruf:
  python scripts/build_portfolio.py                 # Bericht erzeugen
  python scripts/build_portfolio.py --map-only      # nur Zuordnung aktualisieren
  python scripts/build_portfolio.py --out "D:/..."  # anderes Ausgabeverzeichnis
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from build_indices import load_series
from common import CARD_INDEX, FX_CSV, ROOT, SEALED_INDEX, SITE_DATA, read_products

from pokedata import METHOD_VERSION, fx, risk
from pokedata import portfolio as pf
from pokedata.atomicio import read_js_var, write_json, write_text

PROJECT_DIR = os.path.dirname(ROOT)          # eine Ebene über dem Repository
ORDER_BOOK = os.path.join(PROJECT_DIR, "Order book.xlsx")
EXPENDITURES = os.path.join(PROJECT_DIR, "Other Expenditures.xlsx")


def load_benchmarks() -> dict:
    out = {}
    for name, fn in ((SEALED_INDEX, "idx_SPKS.js"), (CARD_INDEX, "idx_SPK500.js")):
        p = os.path.join(SITE_DATA, fn)
        if os.path.isfile(p):
            out[name] = [[d, v] for d, v in read_js_var(p)["series"]]
    mp = os.path.join(SITE_DATA, "markets.js")
    if os.path.isfile(mp):
        mk = read_js_var(mp)
        for n in ("SP500", "GOLD", "BITCOIN"):
            if n in (mk.get("series") or {}):
                out[n] = [[d, v] for d, v in mk["series"][n]]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=PROJECT_DIR, help="Ausgabeverzeichnis")
    ap.add_argument("--order-book", default=ORDER_BOOK)
    ap.add_argument("--map-only", action="store_true")
    ap.add_argument("--no-excel", action="store_true")
    ap.add_argument("--offline-fx", action="store_true",
                    help="keine FX-Abfrage, nur lokalen Cache nutzen")
    args = ap.parse_args()

    if not os.path.isfile(args.order_book):
        print(f"Order Book nicht gefunden: {args.order_book}")
        return 1
    os.makedirs(args.out, exist_ok=True)
    map_path = os.path.join(args.out, "portfolio_map.csv")
    manual_path = os.path.join(args.out, "portfolio_prices_manual.csv")

    from pokedata import quality
    rep = quality.Report()
    lots = pf.load_orders(args.order_book, rep)
    extras = pf.load_expenditures(EXPENDITURES)
    print(f"{len(lots)} Käufe gelesen, {len(extras)} Nebenkostenposten")
    if rep.warnings:
        print("Hinweise zum Order Book:")
        print(rep.render())

    products = read_products()

    # ---- Zuordnung: Vorschläge erzeugen, Nutzerkorrekturen bewahren ----
    existing = pf.load_mapping(map_path)
    suggestions = pf.suggest_mapping([lot.artikel for lot in lots], products)
    merged = pf.refresh_labels(pf.merge_mapping(existing, suggestions), products)
    pf.write_mapping(map_path, merged)
    mapping = pf.load_mapping(map_path)
    auto = sum(1 for r in merged if r.get("status") == "auto")
    unsure = [r for r in merged if r.get("status") in ("unsicher", "offen")]
    print(f"Zuordnung: {auto} automatisch, {len(unsure)} zu prüfen "
          f"-> {os.path.basename(map_path)}")
    for r in unsure:
        print(f"    PRÜFEN  {r['artikel']}  ->  "
              f"{r['product_name'] or '(keine Zuordnung)'}  "
              f"(Score {r['score']}) {r['hinweis']}")
    if args.map_only:
        return 0

    if not os.path.isfile(manual_path):
        write_text(manual_path,
                   "artikel,datum,preis_eur,quelle\n"
                   "# Optional: echte Cardmarket-Preise je Artikel eintragen.\n"
                   "# Diese Zeilen haben Vorrang vor dem TCGplayer-Proxy.\n"
                   "# Beispiel:\n"
                   "# Wachsendes Chaos Display,2026-07-20,168.50,Cardmarket Trend\n",
                   bom=True)
    manual = pf.load_manual_prices(manual_path)

    # ---- Preise + FX ----
    dates, per_product, _var = load_series()
    if not dates:
        print("Keine Preisdaten – zuerst fetch_prices.py ausführen.")
        return 1
    needed = {m["product_id"] for m in mapping.values() if m.get("product_id")}
    panel = {pid: {dates[di]: c for di, c in s.items()}
             for pid, s in per_product.items() if pid in needed}
    rates = fx.update(FX_CSV, start=min(lot.kaufdatum for lot in lots) if lots
                      else "2024-01-01", offline=args.offline_fx)
    if not rates:
        print("Keine FX-Kurse verfügbar (Cache leer und offline) – Abbruch.")
        return 1
    print(f"FX-Kurse: {len(rates)} Tage bis {max(rates)}")

    val = pf.valuate(lots, mapping, panel, rates, manual=manual,
                     products=products)
    s = val.summary
    if s.get("fehler") or "positionen" not in s:
        print(f"Bewertung nicht möglich: {s.get('fehler', 'unbekannt')}")
        print("Prüfen: enthält portfolio_map.csv gültige product_id-Werte?")
        return 1
    print("\nPortfolio:")
    print(f"  Positionen        {s['positionen']} ({s['stueckzahl']} Stück)")
    print(f"  Einstandskosten   {s['kosten_eur']:>12,.2f} EUR")
    print(f"  Marktwert (brutto){s['marktwert_eur']:>12,.2f} EUR")
    print(f"  Marktwert (netto) {s['marktwert_netto_eur']:>12,.2f} EUR "
          f"(nach Verkaufsgebühren)")
    print(f"  P&L brutto        {s['pl_eur']:>12,.2f} EUR  ({s['pl_pct']} %)")
    print(f"  P&L netto         {s['pl_netto_eur']:>12,.2f} EUR  "
          f"({s['pl_netto_pct']} %)")
    print(f"  Proxy-Anteil      {s['proxy_anteil_pct']} % des Marktwerts "
          f"(englische TCGplayer-Preise statt Cardmarket DE)")
    if s["nicht_bewertet"]:
        print(f"  NICHT bewertet    {s['nicht_bewertet']} Positionen "
              f"({s['nicht_bewertet_kosten_eur']:,.2f} EUR Einstand)")
    if s.get("twr_pct") is not None:
        print(f"  Zeitgew. Rendite  {s['twr_pct']:+.2f} %")

    bench = pf.benchmark_comparison(val.twr, load_benchmarks())
    if bench.get("performance_pct"):
        print("  Vergleich (gleicher Zeitraum, Basis 100):")
        for n, v in sorted(bench["performance_pct"].items(),
                           key=lambda kv: -kv[1]):
            print(f"    {n:12s} {v:+8.2f} %")

    nebenkosten = sum(w for _n, _t, w, _a in extras)
    result = {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "method_version": METHOD_VERSION,
        "summary": s,
        "positionen": val.positions,
        "serie": val.series,
        "twr": val.twr,
        "benchmark": bench,
        "nicht_bewertet": val.unmatched,
        "nebenkosten_eur": round(nebenkosten, 2),
        "nebenkosten": [{"name": n, "typ": t, "wert_eur": w, "anzahl": a}
                        for n, t, w, a in extras],
        "risiko": risk.metrics(val.twr, label="Portfolio (TWR)") if val.twr else {},
        "hinweise": [
            "Einstandskosten sind exakt (inkl. Versand, wie gezahlt).",
            "Marktwerte sind Schätzwerte: englische TCGplayer-Marktpreise, "
            "USD->EUR mit EZB-Tageskurs, optional auf die Packungszahl "
            "skaliert. Deutsche Auflagen sind ein anderer Markt – für belastbare "
            "Werte echte Cardmarket-Preise in portfolio_prices_manual.csv "
            "eintragen.",
            "Netto-Werte ziehen die Verkaufsgebühren der jeweiligen Plattform ab "
            "(pokedata/fees.py); Versand trägt üblicherweise der Käufer.",
            "Nebenkosten (Schutzhüllen etc.) sind separat ausgewiesen und NICHT "
            "in den Positionskosten enthalten.",
        ],
    }
    write_json(os.path.join(args.out, "portfolio.json"), result)

    from portfolio_report import write_html
    html_path = os.path.join(args.out, "Portfolio_Bericht.html")
    write_html(html_path, result)
    print(f"\nBericht: {html_path}")

    if not args.no_excel:
        try:
            from portfolio_excel import write_excel
            xlsx_path = os.path.join(args.out, "Portfolio_Analyse.xlsx")
            write_excel(xlsx_path, result)
            print(f"Arbeitsmappe: {xlsx_path}")
        except ImportError as exc:
            print(f"Excel-Export übersprungen ({exc}); openpyxl installieren.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
