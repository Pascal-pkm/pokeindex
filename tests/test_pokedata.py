# -*- coding: utf-8 -*-
"""Tests der gemeinsamen Bibliothek.

Schwerpunkte:
  * Golden Master: die konsolidierte Indexbibliothek muss mit LEGACY_RULES die
    Ergebnisse der alten Implementierung bitgenau reproduzieren. Ohne diesen
    Nachweis ist jede Refaktorierung einer Zeitreihenrechnung wertlos.
  * Klassifikation: der Wortgrenzen-Bug ("victini" enthält "tin") ist als
    Testfall festgeschrieben.
  * Printing-Guard, Hysterese, Validierung, Risiko, Portfolio, Backtest.

Aufruf:  python -m pytest tests -q
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from pokedata import backtest, classify, fees, indexlib, quality, risk, screen  # noqa: E402
from pokedata import portfolio as pf  # noqa: E402
from pokedata.atomicio import read_js_var, write_gzip_csv, write_js_var  # noqa: E402
from pokedata.sources import tcgcsv  # noqa: E402


# ------------------------------------------------------------ Klassifikation
def test_wortgrenzen_bug_victini_ist_keine_sealed():
    """Der ursprüngliche Negativ-Filter ohne Wortgrenzen sortierte Karten mit
    'tin' im Namen (Victini, Tinkaton) als Sealed aus."""
    assert classify.looks_sealed_slug("victini-11") is False
    assert classify.looks_sealed_slug("tinkaton-ex-125") is False
    assert classify.looks_sealed_slug("charizard-vmax-020") is False
    assert classify.looks_sealed_slug("hidden-fates-tin-charizard") is True
    assert classify.looks_sealed_slug("elite-trainer-box") is True


def test_slug_und_name_liefern_gleiche_kategorie():
    paare = [("booster-box-scarlet", "Scarlet & Violet Booster Box", "booster_box"),
             ("elite-trainer-box-red", "Elite Trainer Box Red", "etb"),
             ("charizard-tin", "Charizard Tin", "tin"),
             ("booster-bundle", "Booster Bundle", "bundle"),
             ("theme-deck-blastoise", "Theme Deck Blastoise", "deck")]
    for slug, name, expected in paare:
        assert classify.sealed_category_from_slug(slug) == expected
        assert classify.sealed_category_from_name(name) == expected


def test_einzelkarte_ueber_extended_data():
    is_sealed, cat, num, rar = classify.classify_name(
        "Charizard Booster Box", [{"name": "Number", "value": "004/102"}])
    assert is_sealed == 0 and num == "004/102" and cat is None


def test_junk_wird_ignoriert():
    assert classify.classify_name("Pokemon TCG Online Code Card")[0] == -1
    assert classify.classify_slug("code-card-promo")[0] == -1


# ------------------------------------------------------------------- Indexlib
def _dates(n, start="2026-01-01"):
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def test_adjust_carry_forward_und_guard():
    dates = _dates(10)
    raw = {0: 100, 1: 100, 2: 100, 3: 100, 4: 100, 5: 1000, 7: 100}
    rules = indexlib.IndexRules(outlier_min_history=5, carry_max_days=70)
    adj, conf = indexlib.adjust(raw, dates, rules)
    assert adj[5] == 100 and conf[5] is False      # Ausreißer gehalten
    assert adj[6] == 100 and conf[6] is False      # Carry-Forward
    assert conf[7] is True


def test_carry_forward_endet_nach_grenze():
    dates = _dates(120)
    rules = indexlib.IndexRules(carry_max_days=70)
    adj, _ = indexlib.adjust({0: 500}, dates, rules)
    assert adj[70] == 500
    assert adj[71] is None


def test_zweiter_tag_bestaetigt_ausreisser():
    dates = _dates(12)
    raw = dict.fromkeys(range(6), 100)
    raw[6] = 1000
    raw[7] = 1000
    rules = indexlib.IndexRules(outlier_min_history=5)
    adj, conf = indexlib.adjust(raw, dates, rules)
    assert adj[6] == 100 and conf[6] is False
    assert adj[7] == 1000 and conf[7] is True


def test_printing_guard_verwirft_variantenwechsel():
    universe = {
        1: indexlib.Series(adj=[100, 200], conf=[True, True], raw=[100, 200],
                           variant=["Holofoil", "Reverse Holofoil"]),
        2: indexlib.Series(adj=[100, 110], conf=[True, True], raw=[100, 110],
                           variant=["Holofoil", "Holofoil"]),
    }
    rules_on = indexlib.IndexRules(printing_guard=True)
    rets, dropped = indexlib.daily_returns(universe, [1, 2], 0, 1, rules_on)
    assert dropped == 1 and len(rets) == 1 and abs(rets[0] - 0.1) < 1e-12
    rules_off = indexlib.IndexRules(printing_guard=False)
    rets2, dropped2 = indexlib.daily_returns(universe, [1, 2], 0, 1, rules_off)
    assert dropped2 == 0 and len(rets2) == 2


def test_min_return_pairs_haelt_niveau():
    dates = _dates(3)
    per = {i: {0: 100, 1: 200, 2: 200} for i in range(5)}
    rules = indexlib.IndexRules(size=10, min_return_pairs=10, printing_guard=False)
    univ = indexlib.build_universe(per, dates, rules)
    res = indexlib.compute_index("T", dates, univ, {}, rules)
    assert res["overview"]["level"] == rules.base_level     # unverändert
    assert res["diagnostics"]["days_without_breadth"] == 2


def test_winsor_daempft_einzelausreisser():
    rets = [0.0] * 98 + [10.0, -10.0]
    m = indexlib._winsorized_mean(rets, 0.01)
    assert abs(m) < 0.11        # ohne Winsor wäre der Mittelwert 0, aber die
    # Extremwerte werden auf die 1-%-Quantile gezogen: Ergebnis bleibt klein
    m2 = indexlib._winsorized_mean([0.0] * 98 + [10.0, 10.0], 0.01)
    assert m2 < 0.25            # gedämpft statt 0,2


def test_ew_chain_gleichgewichtet():
    dates = _dates(3)
    raw = {i: {0: 100, 1: 110, 2: 121} for i in range(60)}
    out = indexlib.ew_chain(dates, raw, start_level=100.0, min_pairs=50)
    assert abs(out[-1][1] - 121.0) < 0.5


def test_ew_chain_haelt_bei_zu_wenig_paaren():
    dates = _dates(2)
    raw = {i: {0: 100, 1: 200} for i in range(10)}
    out = indexlib.ew_chain(dates, raw, start_level=100.0, min_pairs=50)
    assert out[-1][1] == 100.0


# ------------------------------------------------- Golden Master (echte Daten)
GOLDEN = os.path.join(ROOT, "tests", "golden")


def _load_daily_panel(daily_dir, limit=None):
    import csv
    files = sorted(f for f in os.listdir(daily_dir) if f.endswith(".csv.gz"))
    if limit:
        files = files[-limit:]
    dates = [f[:-7] for f in files]
    per, var = {}, {}
    for di, f in enumerate(files):
        with gzip.open(os.path.join(daily_dir, f), "rt", encoding="utf-8",
                       newline="") as fh:
            rd = csv.reader(fh)
            next(rd, None)
            for pid, cents, sub in rd:
                pid = int(pid)
                per.setdefault(pid, {})[di] = int(cents)
                var.setdefault(pid, {})[di] = sub
    return dates, per, var


@pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, "data", "daily")),
                    reason="Tagesdaten nicht vorhanden")
def test_golden_master_legacy_reproduziert_altes_ergebnis():
    """Mit LEGACY_RULES muss die neue Bibliothek die zuvor veröffentlichten
    Indexstände exakt treffen. Referenz: tests/golden/legacy_levels.json
    (aus den Artefakten vor der Konsolidierung)."""
    ref_path = os.path.join(GOLDEN, "legacy_levels.json")
    if not os.path.isfile(ref_path):
        pytest.skip("keine Golden-Referenz hinterlegt")
    with open(ref_path, encoding="utf-8") as f:
        ref = json.load(f)

    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import common
    products = common.read_products()
    dates, per, var = _load_daily_panel(os.path.join(ROOT, "data", "daily"))
    dates = [d for d in dates if d <= ref["asof"]]
    n = len(dates)
    per = {p: {di: c for di, c in s.items() if di < n} for p, s in per.items()}
    var = {p: {di: c for di, c in s.items() if di < n} for p, s in var.items()}

    for idx_name, is_sealed in ((ref["card_index"], 0), (ref["sealed_index"], 1)):
        sub = {p: s for p, s in per.items()
               if products.get(p, {}).get("is_sealed") == is_sealed and s}
        univ = indexlib.build_universe(sub, dates, indexlib.LEGACY_RULES)
        res = indexlib.compute_index(idx_name, dates, univ, products,
                                     indexlib.LEGACY_RULES)
        assert res["asof"] == ref["asof"]
        assert res["overview"]["level"] == pytest.approx(
            ref["levels"][idx_name], abs=0.01), (
            f"{idx_name}: {res['overview']['level']} != {ref['levels'][idx_name]}")
        assert res["overview"]["basket"] == ref["baskets"][idx_name]


# ------------------------------------------------------------------- Quality
def test_luecken_erkennung():
    rep = quality.Report()
    missing = quality.check_date_gaps(["2026-01-01", "2026-01-02", "2026-01-05"], rep)
    assert missing == ["2026-01-03", "2026-01-04"]
    assert rep.warnings and not rep.failed


def test_zeilenzahl_absturz_ist_fehler():
    rep = quality.Report()
    counts = {f"2026-01-{i:02d}": 1000 for i in range(1, 11)}
    counts["2026-01-11"] = 100
    quality.check_rowcount(counts, rep)
    assert rep.failed


def test_preis_plausibilitaet():
    rep = quality.Report()
    quality.check_prices([(1, 100, "a"), (1, 200, "a"), (2, -5, "b")], rep)
    assert len([e for e in rep.errors if "doppelte" in e]) == 1
    assert len([e for e in rep.errors if "nicht-positive" in e]) == 1


def test_index_sanity_grosser_sprung():
    rep = quality.Report()
    res = {"asof": "2026-01-02", "rows": [1],
           "overview": {"level": 2000.0, "prev": 1000.0},
           "diagnostics": {"carried_share_last": 0.0}}
    quality.check_index_result(res, rep, "X")
    assert rep.failed


# ---------------------------------------------------------------- Preiswahl
def test_choose_price_ohne_first_edition():
    rows = [{"subTypeName": "1st Edition Holofoil", "marketPrice": 9999.0},
            {"subTypeName": "Holofoil", "marketPrice": 100.0},
            {"subTypeName": "Reverse Holofoil", "marketPrice": 80.0}]
    assert tcgcsv.choose_price(rows) == (100.0, "Holofoil")


def test_choose_price_haelt_vortags_printing():
    rows = [{"subTypeName": "Holofoil", "marketPrice": 100.0},
            {"subTypeName": "Reverse Holofoil", "marketPrice": 120.0}]
    assert tcgcsv.choose_price(rows) == (120.0, "Reverse Holofoil")
    assert tcgcsv.choose_price(rows, "Holofoil") == (100.0, "Holofoil")


def test_choose_price_wechselt_wenn_printing_verschwindet():
    rows = [{"subTypeName": "Reverse Holofoil", "marketPrice": 120.0}]
    assert tcgcsv.choose_price(rows, "Holofoil") == (120.0, "Reverse Holofoil")


def test_hysterese_grenze():
    import common
    known = {1: {"is_sealed": 0}}
    assert common.store_threshold(1, known) == common.KEEP_STORE_PRICE
    assert common.store_threshold(99, known) == common.MIN_STORE_PRICE
    assert common.KEEP_STORE_PRICE < common.MIN_STORE_PRICE


# -------------------------------------------------------------------- Risiko
def test_risk_metrics_grundfall():
    series = [[f"2026-01-{i:02d}", 100 * (1.01 ** (i - 1))] for i in range(1, 31)]
    m = risk.metrics(series, rf=0.0, label="T")
    assert m["rendite_gesamt_pct"] == pytest.approx(33.5, abs=0.5)
    assert m["vola_pa_pct"] == pytest.approx(0.0, abs=1e-6)
    assert m["max_drawdown_pct"] == 0.0
    assert m["positive_tage_pct"] == 100.0


def test_max_drawdown():
    series = [["2026-01-01", 100], ["2026-01-02", 120], ["2026-01-03", 60],
              ["2026-01-04", 90]]
    dd, peak, trough = risk.max_drawdown(series)
    assert dd == -50.0 and peak == "2026-01-02" and trough == "2026-01-03"


def test_korrelation_perfekt_und_gegenlaeufig():
    a = [[f"2026-01-{i:02d}", 100 + i] for i in range(1, 21)]
    b = [[f"2026-01-{i:02d}", 200 + 2 * i] for i in range(1, 21)]
    c, n = risk.correlation(a, b)
    assert n == 19 and c == pytest.approx(1.0, abs=0.01)


def test_rebase():
    s = [["2026-01-01", 50], ["2026-01-02", 75]]
    assert risk.rebase(s, 100.0) == [["2026-01-01", 100.0], ["2026-01-02", 150.0]]


# ------------------------------------------------------------------ Gebühren
def test_gebuehren_netto_und_breakeven():
    cm = fees.model_for("cardmarket.com")
    netto = cm.net_proceeds(100.0)
    assert netto == pytest.approx(94.0, abs=0.01)      # 5 % + 1 %
    be = fees.breakeven_price(94.0, "cardmarket.com")
    assert be == pytest.approx(100.0, abs=0.05)


def test_ebay_fixgebuehr():
    eb = fees.model_for("ebay.de")
    assert eb.net_proceeds(10.0) == pytest.approx(10 - 1.1 - 0.35, abs=0.01)


def test_unbekannte_plattform_faellt_auf_default():
    assert fees.model_for("irgendwas").name == fees.DEFAULT_MODEL.name


# ----------------------------------------------------------------- Screening
def _synth_panel():
    """Zwei Produkte: eines günstig+stabil, eines teuer+volatil."""
    days = _dates(400, "2025-01-01")
    panel = {}
    stable = {}
    for i, d in enumerate(days):
        stable[d] = 10000 if i < 200 else 8000        # gefallen, dann stabil
    panel[1] = stable
    vol = {}
    for i, d in enumerate(days):
        vol[d] = 10000 + (3000 if i % 2 else -3000) + i * 20
    panel[2] = vol
    return days, panel


def test_screening_bewertet_guenstig_stabil_hoeher():
    days, panel = _synth_panel()
    rows = screen.score_universe(panel, days[-1], {1: {"name": "A"}, 2: {"name": "B"}})
    by = {r["product_id"]: r for r in rows}
    assert by[1]["stabilitaet"] >= by[2]["stabilitaet"]
    assert by[1]["guenstigkeit"] >= by[2]["guenstigkeit"]


def test_screening_flaggt_hohe_vola():
    days, panel = _synth_panel()
    rows = screen.score_universe(panel, days[-1], {})
    b = [r for r in rows if r["product_id"] == 2][0]
    assert "hohe Volatilität" in b["risiken"] or b["vola_pa_pct"] > 50


def test_series_features_konsolidierung():
    days = _dates(50)
    cents = [1000] * 50
    f = screen.series_features(days, cents)
    assert f["consolidation_days"] == 50
    assert f["discount_ath"] == 0.0


# ------------------------------------------------------------------ Backtest
def test_forward_return_und_lookahead():
    s = {"2026-01-01": 100, "2026-02-01": 120}
    assert backtest.forward_return(s, "2026-01-01", 31) == pytest.approx(0.2)
    assert backtest.forward_return(s, "2026-01-01", 400) is None


def test_spearman_monoton():
    assert backtest.spearman([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    assert backtest.spearman([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) == pytest.approx(-1.0)


def test_rebalance_dates_respektiert_horizont():
    days = _dates(500, "2025-01-01")
    out = backtest.rebalance_dates(days, 30, 90, 200)
    assert out and out[0] >= "2025-07-20"
    assert dt.date.fromisoformat(out[-1]) <= dt.date.fromisoformat(days[-1]) - dt.timedelta(days=90)


# ----------------------------------------------------------------- Portfolio
def test_namensbruecke_setzuordnung():
    from pokedata import names
    assert names.detect_set("Wachsendes Chaos Top Trainer Box")[1] == "ME04: Chaos Rising"
    assert names.detect_set("Optimale Ordnung Display")[1] == "ME03: Perfect Order"
    assert names.detect_set("Weiße Flammen Top Trainer Box")[1] == "SV: White Flare"
    assert names.detect_type("Wachsendes Chaos Top Trainer Box")[0] == "etb"
    assert names.detect_type("Astralglanz 36er Booster Display")[0] == "booster_box"
    assert names.detect_pack_count("Fatale Flammen 18er Display") == 18


def test_mapping_vorschlag_trifft_typ():
    products = {
        10: {"name": "ME04: Chaos Rising Elite Trainer Box", "is_sealed": "1",
             "group_name": "ME04: Chaos Rising", "sealed_cat": "etb"},
        11: {"name": "ME04: Chaos Rising Booster Box", "is_sealed": "1",
             "group_name": "ME04: Chaos Rising", "sealed_cat": "booster_box"},
    }
    rows = pf.suggest_mapping(["Wachsendes Chaos Top Trainer Box"], products)
    assert rows[0]["product_id"] == 10
    assert rows[0]["score"] >= 0.55


def test_valuation_pl_und_twr():
    lots = [pf.Lot("Test Display", 2, 200.0, 100.0, "2026-01-01", "cardmarket.com")]
    mapping = {pf.nm.norm("Test Display"): {"product_id": 5, "pack_factor": 1.0,
                                            "product_name": "X", "group_name": "Y"}}
    panel = {5: {"2026-01-01": 12000, "2026-01-02": 13000}}   # 120 -> 130 USD
    rates = {"2026-01-01": 1.0, "2026-01-02": 1.0}            # 1 USD = 1 EUR
    val = pf.valuate(lots, mapping, panel, rates)
    pos = val.positions[0]
    assert pos["wert_eur"] == pytest.approx(260.0)
    assert pos["pl_eur"] == pytest.approx(60.0)
    assert pos["pl_netto_eur"] < pos["pl_eur"]          # Gebühren wirken
    assert val.summary["proxy_anteil_pct"] == 100.0
    assert val.twr[-1][1] > 100                          # Wertsteigerung


def test_valuation_manuelle_preise_gewinnen():
    lots = [pf.Lot("Test Box", 1, 50.0, 50.0, "2026-01-01", "cardmarket.com")]
    mapping = {pf.nm.norm("Test Box"): {"product_id": 7, "pack_factor": 1.0}}
    panel = {7: {"2026-01-01": 10000, "2026-01-02": 10000}}
    rates = {"2026-01-01": 1.0, "2026-01-02": 1.0}
    manual = {pf.nm.norm("Test Box"): [("2026-01-02", 42.0, "Cardmarket")]}
    val = pf.valuate(lots, mapping, panel, rates, manual=manual)
    assert val.positions[0]["wert_eur"] == pytest.approx(42.0)
    assert val.positions[0]["is_proxy"] == 0


def test_valuation_ohne_zuordnung_wird_ausgewiesen():
    lots = [pf.Lot("Unbekannt", 1, 30.0, 30.0, "2026-01-01", "ebay.de")]
    panel = {9: {"2026-01-01": 1000, "2026-01-02": 1000}}
    val = pf.valuate(lots, {}, panel, {"2026-01-01": 1.0, "2026-01-02": 1.0})
    assert val.summary["nicht_bewertet"] == 1
    assert val.summary["nicht_bewertet_kosten_eur"] == 30.0


def test_pack_factor_skaliert_bewertung():
    lots = [pf.Lot("18er Display", 1, 100.0, 100.0, "2026-01-01", "ebay.de")]
    mapping = {pf.nm.norm("18er Display"): {"product_id": 3, "pack_factor": 0.5}}
    panel = {3: {"2026-01-01": 20000, "2026-01-02": 20000}}
    val = pf.valuate(lots, mapping, panel, {"2026-01-01": 1.0, "2026-01-02": 1.0})
    assert val.positions[0]["preis_stueck_eur"] == pytest.approx(100.0)


# ------------------------------------------------------------------ Atomic IO
def test_atomic_js_roundtrip(tmp_path):
    p = str(tmp_path / "x.js")
    write_js_var(p, "TEST", {"a": [1, 2, 3]})
    assert read_js_var(p) == {"a": [1, 2, 3]}


def test_gzip_csv_deterministisch(tmp_path):
    p1, p2 = str(tmp_path / "a.csv.gz"), str(tmp_path / "b.csv.gz")
    write_gzip_csv(p1, ["a", "b"], [[1, 2]])
    write_gzip_csv(p2, ["a", "b"], [[1, 2]])
    with open(p1, "rb") as f1, open(p2, "rb") as f2:
        assert f1.read() == f2.read()


def test_atomic_write_laesst_bei_fehler_alten_stand(tmp_path):
    from pokedata.atomicio import atomic_path
    p = str(tmp_path / "keep.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("alt")
    with pytest.raises(RuntimeError), atomic_path(p) as tmp:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("neu")
        raise RuntimeError("Abbruch")
    with open(p, encoding="utf-8") as f:
        assert f.read() == "alt"
    assert len(os.listdir(tmp_path)) == 1        # kein Temp-Rest
