# -*- coding: utf-8 -*-
"""
Gemeinsame Helfer für den Pokémon-Index.

Datenhaltung (git-freundlich, keine wachsende Datenbank):
  data/daily/JJJJ-MM-TT.csv.gz   ein Preistag: product_id,cents,sub_type
  data/products.csv.gz           Stammdaten aller getrackten Produkte
Die Indexberechnung liest alle Tagesdateien und rechnet die komplette
Historie deterministisch neu – kein Zustand, der kaputtgehen kann.
"""
import csv
import gzip
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DAILY_DIR = os.path.join(ROOT, "data", "daily")
PRODUCTS_CSV = os.path.join(ROOT, "data", "products.csv.gz")
SITE_DATA = os.path.join(ROOT, "site", "data")

CATEGORY = 3          # TCGplayer-Kategorie "Pokemon"
BASE_URL = "https://tcgcsv.com/tcgplayer"
ARCHIVE_URL = "https://tcgcsv.com/archive/tcgplayer/prices-{d}.ppmd.7z"
ARCHIVE_START = "2024-02-08"   # Frühester Tag im tcgcsv-Archiv
USER_AGENT = "PokeIndex-Privat/1.0 (privates Forschungsprojekt)"

# Index-Regeln (wie in der Methodik der Vorlage-Website beschrieben)
INDEX_SIZE = 500          # Top 500 nach Preis
CARRY_MAX_DAYS = 70       # Letzten Preis max. 70 Tage fortschreiben (†)
OUTLIER_HI = 2.5          # Preis > 2,5x Median -> verdächtig, wird gehalten
OUTLIER_LO = 0.4          # Preis < 0,4x Median -> verdächtig, wird gehalten
OUTLIER_WINDOW = 14       # Median über die letzten 14 bestätigten Preise
OUTLIER_MIN_HISTORY = 5   # Guard erst ab 5 bestätigten Preisen aktiv
MIN_STORE_PRICE = 25.0    # Karten unter 25 USD nicht speichern (Top-500-Cutoff ~200 USD)

CARD_INDEX = "SPK500"
SEALED_INDEX = "SPKS"
BASE_LEVEL = 1000.0       # Startniveau beider Indizes

SEALED_CATS = [
    ("booster_box",    re.compile(r"booster (display )?box|\bdisplay\b", re.I)),
    ("etb",            re.compile(r"elite trainer", re.I)),
    ("bundle",         re.compile(r"booster bundle|\bbundle\b", re.I)),
    ("pack_blister",   re.compile(r"booster pack|sleeved booster|blister|checklane|3.?pack|1.?pack", re.I)),
    ("tin",            re.compile(r"\btins?\b", re.I)),
    ("deck",           re.compile(r"theme deck|battle deck|starter deck|deck kit|league battle|build ?& ?battle|\bdecks?\b", re.I)),
    ("collection_box", re.compile(r"collection|premium|box set|\bbox\b|pin |figure|poster|vault|stadium|academy|carry case|mini portfolio", re.I)),
]
JUNK_RE = re.compile(r"code card|\blot\b|player placement", re.I)

PRODUCT_FIELDS = ["product_id", "name", "clean_name", "group_id", "group_name",
                  "number", "rarity", "is_sealed", "sealed_cat", "url"]


# ---------------------------------------------------------------- Stammdaten
def read_products():
    """dict product_id -> dict mit PRODUCT_FIELDS."""
    if not os.path.isfile(PRODUCTS_CSV):
        return {}
    out = {}
    with gzip.open(PRODUCTS_CSV, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row["product_id"] = int(row["product_id"])
            row["is_sealed"] = int(row["is_sealed"])
            out[row["product_id"]] = row
    return out


def write_products(products):
    os.makedirs(os.path.dirname(PRODUCTS_CSV), exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=PRODUCT_FIELDS)
    w.writeheader()
    for pid in sorted(products):
        w.writerow(products[pid])
    with gzip.open(PRODUCTS_CSV, "wt", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


# --------------------------------------------------------------- Tagespreise
def daily_path(datum):
    return os.path.join(DAILY_DIR, f"{datum}.csv.gz")


def have_dates():
    if not os.path.isdir(DAILY_DIR):
        return []
    return sorted(f[:-7] for f in os.listdir(DAILY_DIR) if f.endswith(".csv.gz"))


def write_daily(datum, rows):
    """rows: Iterable von (product_id, cents, sub_type)."""
    os.makedirs(DAILY_DIR, exist_ok=True)
    with gzip.open(daily_path(datum), "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "cents", "sub_type"])
        for r in sorted(rows):
            w.writerow(r)


def read_daily(datum):
    with gzip.open(daily_path(datum), "rt", encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        next(rd)
        return [(int(a), int(b), c) for a, b, c in rd]


# ------------------------------------------------------------- Klassifikation
def classify_product(name, extended):
    """(is_sealed, sealed_cat, number, rarity); is_sealed -1 = ignorieren."""
    number, rarity = None, None
    for e in (extended or []):
        n = (e.get("name") or "").lower()
        if n == "number":
            number = e.get("value")
        elif n == "rarity":
            rarity = e.get("value")
    if number or rarity:               # Einzelkarte
        return 0, None, number, rarity
    if JUNK_RE.search(name or ""):     # Code-Karten, Lots usw.
        return -1, None, None, None
    for cat, rx in SEALED_CATS:
        if rx.search(name or ""):
            return 1, cat, None, None
    return 1, "sonstiges", None, None


def choose_price(price_rows):
    """Wertvollstes reguläres Printing; '1st Edition' ausgeschlossen.
    -> (marketPrice, subTypeName) oder None."""
    best = None
    for p in price_rows:
        sub = p.get("subTypeName") or ""
        if "1st edition" in sub.lower():
            continue
        m = p.get("marketPrice")
        if m is None:
            continue
        if best is None or m > best[0]:
            best = (m, sub)
    return best
