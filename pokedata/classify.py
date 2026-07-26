# -*- coding: utf-8 -*-
"""Einheitliche Produktklassifikation – EIN Regelwerk für Namen und Slugs.

Vorher existierten drei divergierende Varianten:
  * karten_scraper.py   Negativ-Regex auf URL-Slugs, OHNE Wortgrenzen
                        -> Slugs wie "victini-tin" bzw. "vic-tin-i" wurden
                           fälschlich als Sealed erkannt und aussortiert
  * sealed_scraper.py    Positiv-Regex auf Slugs, MIT Wortgrenzen (gefixt)
  * scripts/common.py    Namens-Regex mit anderen Kategorien
Folge: dasselbe Produkt landete je nach Pfad in unterschiedlichen Klassen.

Hier gilt: eine Kategorienliste (SEALED_CATEGORIES), zwei Eintrittspunkte
(`classify_name` für Klartextnamen, `classify_slug` für URL-Slugs). Beide
liefern denselben Kategorieschlüssel.

Kategorieschlüssel (stabil, wird in Daten/Website persistiert):
  booster_box, etb, bundle, pack_blister, tin, deck, collection_box, sonstiges
"""
from __future__ import annotations

import re

# --------------------------------------------------------------- Kategorien
# Reihenfolge = Priorität. Spezifische Muster VOR generischen ("box" zuletzt).
# Jeder Eintrag: (schlüssel, label, namensmuster, slugmuster)
SEALED_CATEGORIES = [
    # Ein Case enthält mehrere Displays und kostet ein Vielfaches. Vorher lief
    # es unter "booster_box" – beim Portfolio-Matching wurde dadurch ein
    # deutsches Display einem Case zugeordnet und um ein Mehrfaches zu hoch
    # bewertet. Eigene Kategorie, VOR booster_box geprüft.
    ("case", "Case (Sammelkarton)",
     # "Carry Case"/"Card Case" sind Zubehör, kein Sammelkarton -> ausgenommen.
     r"booster\s*(box|display)\s*case|\bcase\s*of\b|sealed\s*case|"
     r"(?<!carry )(?<!card )(?<!deck )(?<!storage )\bcase\s*$",
     r"booster-(box|display)-case|^case-|"
     r"(?<!carry)(?<!card)(?<!deck)(?<!storage)-case$"),
    ("booster_box", "Booster Box",
     r"booster\s*(display\s*)?box|\bdisplay\b",
     r"booster-box|\bdisplay\b"),
    ("etb", "Elite Trainer Box",
     r"elite\s*trainer|\betb\b|top\s*trainer",
     r"elite-trainer|\betb\b|top-trainer"),
    ("bundle", "Booster Bundle",
     r"booster\s*bundle|\bbundle\b",
     r"booster-bundle|\bbundle\b"),
    ("pack_blister", "Pack / Blister",
     r"booster\s*pack|sleeved\s*booster|blister|checklane|\d\s*[- ]?pack\b",
     r"booster-pack|sleeved|blister|checklane|\d-pack"),
    ("tin", "Tin",
     r"\btins?\b",
     r"\btins?\b"),
    ("deck", "Deck",
     r"theme\s*deck|battle\s*deck|starter\s*deck|deck\s*kit|league\s*battle|"
     r"build\s*&?\s*battle|\bdecks?\b",
     r"theme-deck|battle-deck|starter-deck|deck-kit|league-battle|"
     r"build-(and|&)-battle|\bdecks?\b"),
    ("collection_box", "Collection / Premium",
     r"collection|premium|box\s*set|\bbox\b|\bpin\b|figure|poster|vault|"
     r"stadium|academy|carry\s*case|card\s*case|portfolio|binder|album|"
     r"gift\s*set|treasure\s*chest|surprise\s*box",
     r"collection|premium|box-set|-box$|\bpins?\b|figure|poster|vault|"
     r"stadium|academy|carry-case|portfolio|binder|album|gift-set"),
]

CATEGORY_LABELS = {k: label for k, label, _n, _s in SEALED_CATEGORIES}
CATEGORY_LABELS["sonstiges"] = "Sonstiges"

# Nicht handelbare / für Preisindizes unbrauchbare Artikel.
JUNK_NAME_RE = re.compile(
    r"code\s*card|online\s*code|\blot\b|player\s*placement|"
    r"\bproxy\b|\bdamaged\b|\bempty\b|\bsealed\s*bag\b", re.I)
JUNK_SLUG_RE = re.compile(
    r"code-card|online-code|\blot\b|player-placement|\bproxy\b|\bempty\b", re.I)

_NAME_RX = [(k, re.compile(n, re.I)) for k, _l, n, _s in SEALED_CATEGORIES]
_SLUG_RX = [(k, re.compile(s, re.I)) for k, _l, _n, s in SEALED_CATEGORIES]

# Wird für Sealed-Erkennung auf Slug-Basis genutzt (Positiv-Filter).
ANY_SEALED_SLUG_RE = re.compile(
    "|".join(f"(?:{s})" for _k, _l, _n, s in SEALED_CATEGORIES), re.I)


def _norm_slug(slug: str) -> str:
    """Slug so normalisieren, dass \\b an Bindestrichen greift."""
    return re.sub(r"[^a-z0-9]+", "-", (slug or "").lower())


def is_junk_name(name: str) -> bool:
    return bool(JUNK_NAME_RE.search(name or ""))


def is_junk_slug(slug: str) -> bool:
    return bool(JUNK_SLUG_RE.search(_norm_slug(slug)))


def sealed_category_from_name(name: str) -> str:
    n = name or ""
    for key, rx in _NAME_RX:
        if rx.search(n):
            return key
    return "sonstiges"


def sealed_category_from_slug(slug: str) -> str:
    s = _norm_slug(slug)
    for key, rx in _SLUG_RX:
        if rx.search(s):
            return key
    return "sonstiges"


def looks_sealed_slug(slug: str) -> bool:
    """True, wenn der URL-Slug ein Sealed-Produkt beschreibt.

    Wortgrenzen sind entscheidend: 'victini' enthält 'tin', ist aber eine
    Einzelkarte. `_norm_slug` macht Bindestriche zu Wortgrenzen, sodass nur
    ein eigenständiges Segment 'tin' zählt.
    """
    s = _norm_slug(slug)
    if is_junk_slug(s):
        return False
    return bool(ANY_SEALED_SLUG_RE.search(s))


def classify_slug(slug: str) -> tuple[int, str | None]:
    """(is_sealed, kategorie) für einen URL-Slug. is_sealed: 1/0, -1 = ignorieren."""
    s = _norm_slug(slug)
    if is_junk_slug(s):
        return -1, None
    if looks_sealed_slug(s):
        return 1, sealed_category_from_slug(s)
    return 0, None


def classify_name(name: str, extended=None) -> tuple[int, str | None, str | None, str | None]:
    """Klassifikation eines TCGplayer-Produkts.

    extended: TCGplayer-`extendedData`. Enthält es Nummer oder Seltenheit,
    ist es zwingend eine Einzelkarte (verlässlicher als jedes Namensmuster).

    Rückgabe: (is_sealed, sealed_cat, number, rarity); is_sealed -1 = ignorieren.
    """
    number = rarity = None
    for e in (extended or []):
        key = (e.get("name") or "").lower()
        if key == "number":
            number = e.get("value")
        elif key == "rarity":
            rarity = e.get("value")
    if number or rarity:
        return 0, None, number, rarity
    if is_junk_name(name):
        return -1, None, None, None
    return 1, sealed_category_from_name(name), None, None
