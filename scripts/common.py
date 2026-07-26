# -*- coding: utf-8 -*-
"""Pfade, Parameter und Datenzugriff der Website-Pipeline.

Die Fachlogik (Klassifikation, Index, Validierung, Risiko, Portfolio) liegt
seit der Konsolidierung in `pokedata/` und wird von hier nur noch
weiterverwendet – vorher enthielt diese Datei eigene Regex-Regeln und
Parameter, die von den anderen Teilsystemen abwichen.

Datenhaltung (git-freundlich, kein wachsender Zustand):
  data/daily/JJJJ-MM-TT.csv.gz   ein Preistag: product_id,cents,sub_type
  data/products.csv.gz           Stammdaten aller getrackten Produkte
  data/fx_usd_eur.csv            EZB-Tagesreferenzkurse (Cache)
Die Indexberechnung liest alle Tagesdateien und rechnet die komplette Historie
deterministisch neu.
"""
from __future__ import annotations

import csv
import gzip
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:                     # pokedata importierbar machen
    sys.path.insert(0, ROOT)

from pokedata import classify, indexlib  # noqa: E402
from pokedata.atomicio import write_gzip_csv, write_gzip_dictcsv  # noqa: E402
from pokedata.sources import tcgcsv  # noqa: E402

DAILY_DIR = os.path.join(ROOT, "data", "daily")
PRODUCTS_CSV = os.path.join(ROOT, "data", "products.csv.gz")
FX_CSV = os.path.join(ROOT, "data", "fx_usd_eur.csv")
SITE_DATA = os.path.join(ROOT, "site", "data")
DATA_DIR = os.path.join(ROOT, "data")

# Quelle
CATEGORY = tcgcsv.CATEGORY_POKEMON
BASE_URL = tcgcsv.BASE_URL
ARCHIVE_URL = tcgcsv.ARCHIVE_URL
ARCHIVE_START = tcgcsv.ARCHIVE_START
USER_AGENT = tcgcsv.USER_AGENT

# ------------------------------------------------------------- Index-Regeln
INDEX_SIZE = 500
CARRY_MAX_DAYS = 70
OUTLIER_HI = 2.5
OUTLIER_LO = 0.4
OUTLIER_WINDOW = 14
OUTLIER_MIN_HISTORY = 5

# Mindestbreite für eine Indexbewegung: 20 % der Indexgröße statt vorher 20
# absolut. Mit 20 von 500 Mitgliedern konnten 4 % der Mitglieder das Niveau
# bewegen – zu wenig, um "gleichgewichteter Mittelwert des Index" zu heißen.
MIN_RETURN_PAIRS = int(INDEX_SIZE * 0.2)
RETURN_WINSOR = 0.01

# Zensur-Grenzen für Einzelkarten (Sealed wird immer gespeichert):
#   Neuaufnahme ab MIN_STORE_PRICE, Beibehaltung bis KEEP_STORE_PRICE.
# Die Hysterese verhindert, dass Karten am Rand des Universums beim
# Unterschreiten der Grenze aus den Daten fallen (die Zensur entfernt genau
# die Verlierer und erzeugt damit einen Aufwärts-Bias in Ranking und Basket).
MIN_STORE_PRICE = 25.0
KEEP_STORE_PRICE = 15.0

CARD_INDEX = "SPK500"
SEALED_INDEX = "SPKS"
CS2_INDEX = "CS2500"
BASE_LEVEL = indexlib.BASE_LEVEL

INDEX_RULES = indexlib.IndexRules(
    size=INDEX_SIZE, carry_max_days=CARRY_MAX_DAYS, outlier_hi=OUTLIER_HI,
    outlier_lo=OUTLIER_LO, outlier_window=OUTLIER_WINDOW,
    outlier_min_history=OUTLIER_MIN_HISTORY, return_winsor=RETURN_WINSOR,
    min_return_pairs=MIN_RETURN_PAIRS, printing_guard=True,
    base_level=BASE_LEVEL, label="spk-2026-07")

PRODUCT_FIELDS = ["product_id", "name", "clean_name", "group_id", "group_name",
                  "number", "rarity", "is_sealed", "sealed_cat", "url"]


# ---------------------------------------------------------------- Stammdaten
def read_products() -> dict:
    if not os.path.isfile(PRODUCTS_CSV):
        return {}
    out = {}
    with gzip.open(PRODUCTS_CSV, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row["product_id"] = int(row["product_id"])
            row["is_sealed"] = int(row["is_sealed"])
            out[row["product_id"]] = row
    return out


def write_products(products: dict) -> None:
    write_gzip_dictcsv(PRODUCTS_CSV, PRODUCT_FIELDS,
                       (products[pid] for pid in sorted(products)))


# --------------------------------------------------------------- Tagespreise
def daily_path(datum: str) -> str:
    return os.path.join(DAILY_DIR, f"{datum}.csv.gz")


def have_dates() -> list:
    if not os.path.isdir(DAILY_DIR):
        return []
    return sorted(f[:-7] for f in os.listdir(DAILY_DIR) if f.endswith(".csv.gz"))


def write_daily(datum: str, rows) -> None:
    """rows: Iterable von (product_id, cents, sub_type) – atomar geschrieben."""
    write_gzip_csv(daily_path(datum), ["product_id", "cents", "sub_type"],
                   sorted(rows))


def read_daily(datum: str) -> list:
    with gzip.open(daily_path(datum), "rt", encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        next(rd, None)
        return [(int(a), int(b), c) for a, b, c in rd]


def read_last_daily() -> dict:
    """{product_id: sub_type} des jüngsten vorhandenen Tages.

    Grundlage der Printing-Stabilität: der nächste Abzug behält das Printing
    des Vortags bei, solange dafür ein Marktpreis existiert.
    """
    dates = have_dates()
    if not dates:
        return {}
    return {pid: sub for pid, _cents, sub in read_daily(dates[-1])}


# ------------------------------------------------------------- Klassifikation
def classify_product(name, extended):
    """(is_sealed, sealed_cat, number, rarity); is_sealed -1 = ignorieren."""
    return classify.classify_name(name, extended)


def choose_price(price_rows, prefer_sub=None):
    """Wertvollstes reguläres Printing, bevorzugt das Printing des Vortags."""
    return tcgcsv.choose_price(price_rows, prefer_sub)


def store_threshold(pid: int, known_products: dict) -> float:
    """Speichergrenze für Einzelkarten mit Hysterese."""
    return KEEP_STORE_PRICE if pid in known_products else MIN_STORE_PRICE
