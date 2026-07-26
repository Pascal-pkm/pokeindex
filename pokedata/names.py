# -*- coding: utf-8 -*-
"""Deutsch-englische Namensbrücke für das Portfolio-Matching.

Das reale Order Book enthält ausschließlich deutschsprachige Produkte
("Wachsendes Chaos Top Trainer Box"), die Preisquelle (TCGplayer/tcgcsv)
kennt nur englische Produkte ("ME04: Chaos Rising Elite Trainer Box").
Ohne diese Brücke lässt sich kein Bestand bewerten.

Wichtig für die Interpretation: deutschsprachige Produkte sind ein anderes
Gut als die englischsprachigen (eigene Auflagen, eigener Markt, Cardmarket
statt TCGplayer). Die Zuordnung dient der Bewertungs-NÄHERUNG; jede damit
erzeugte Bewertung wird als Proxy gekennzeichnet (siehe portfolio.py).
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- Set-Namen
# Deutscher Erweiterungsname -> englischer group_name in products.csv.gz
SET_DE_EN = {
    # Mega-Entwicklung-Zyklus (2025/2026)
    "mega entwicklung": "ME01: Mega Evolution",
    "mega-entwicklung": "ME01: Mega Evolution",
    "fatale flammen": "ME02: Phantasmal Flames",
    "optimale ordnung": "ME03: Perfect Order",
    "wachsendes chaos": "ME04: Chaos Rising",
    "pechschwarz": "ME05: Pitch Black",
    "erhabene helden": "ME: Ascended Heroes",
    "30 jahre": "ME: 30th Celebration",
    "erste partner kollektion": "First Partner Collection 2026",
    "erste-partner-kollektion": "First Partner Collection 2026",
    # Karmesin & Purpur (Scarlet & Violet)
    "karmesin und purpur": "SV01: Scarlet & Violet Base Set",
    "karmesin & purpur": "SV01: Scarlet & Violet Base Set",
    "entwicklungen in paldea": "SV02: Paldea Evolved",
    "obsidianflammen": "SV03: Obsidian Flames",
    "paradoxrift": "SV04: Paradox Rift",
    "zeitgeschwindigkeit": "SV05: Temporal Forces",
    "maskerade im zwielicht": "SV06: Twilight Masquerade",
    "stellarkrone": "SV07: Stellar Crown",
    "funkelnde fluten": "SV08: Surging Sparks",
    "reisegefaehrten": "SV09: Journey Together",
    "reisegefährten": "SV09: Journey Together",
    "ewige rivalen": "SV10: Destined Rivals",
    "schwarze blitze": "SV: Black Bolt",
    "weisse flammen": "SV: White Flare",
    "weiße flammen": "SV: White Flare",
    "paldeas schicksale": "SV: Paldean Fates",
    "nebel der sagen": "SV: Shrouded Fable",
    "prismatische entwicklungen": "SV: Prismatic Evolutions",
    "pokemon 151": "SV: Scarlet & Violet 151",
    "karmesin und purpur 151": "SV: Scarlet & Violet 151",
    # Schwert & Schild
    "schwert und schild": "SWSH01: Sword & Shield Base Set",
    "rebellclash": "SWSH02: Rebel Clash",
    "flammende finsternis": "SWSH03: Darkness Ablaze",
    "farbenschock": "SWSH04: Vivid Voltage",
    "kampfstile": "SWSH05: Battle Styles",
    "schaurige herrschaft": "SWSH06: Chilling Reign",
    "himmelsherrscher": "SWSH07: Evolving Skies",
    "fusionsangriff": "SWSH08: Fusion Strike",
    "strahlende sterne": "SWSH09: Brilliant Stars",
    "astralglanz": "SWSH10: Astral Radiance",
    "verlorener urspung": "SWSH11: Lost Origin",
    "verlorener ursprung": "SWSH11: Lost Origin",
    "silberne sturmwinde": "SWSH12: Silver Tempest",
    "zenit der koenige": "SWSH: Crown Zenith",
    "zenit der könige": "SWSH: Crown Zenith",
    "glaenzendes schicksal": "Shining Fates",
    "glänzendes schicksal": "Shining Fates",
    "champions weg": "SWSH: Champion's Path",
    "champion's path": "SWSH: Champion's Path",
    # Sonne & Mond / XY (nur die im Bestand relevanten)
    "strahlende legenden": "Shining Legends",
    "evolution": "XY - Evolutions",
}

# ------------------------------------------------------------ Produkttypen
# Deutsche Typbezeichnung -> (kategorie, englische Kernbegriffe)
TYPE_DE = [
    ("top trainer box", "etb", ["elite trainer box"]),
    ("ttb", "etb", ["elite trainer box"]),
    ("elite trainer box", "etb", ["elite trainer box"]),
    ("boosterbundle", "bundle", ["booster bundle"]),
    ("booster bundle", "bundle", ["booster bundle"]),
    ("booster display", "booster_box", ["booster box", "booster display"]),
    ("display", "booster_box", ["booster box", "booster display"]),
    ("booster box", "booster_box", ["booster box"]),
    ("premium-kollektion", "collection_box", ["premium collection"]),
    ("premium kollektion", "collection_box", ["premium collection"]),
    ("ultra-premium-kollektion", "collection_box", ["ultra premium collection"]),
    ("kollektion", "collection_box", ["collection"]),
    ("blister", "pack_blister", ["blister", "pack"]),
    ("booster", "pack_blister", ["booster pack"]),
    ("tin", "tin", ["tin"]),
    ("deck", "deck", ["deck"]),
    ("case", "booster_box", ["case"]),
]

# Pokémon-Namen, die in Produktnamen auftauchen (Bestand + häufige Fälle)
POKEMON_DE_EN = {
    "enton": "psyduck", "iksbat": "crobat", "wulaosu": "urshifu",
    "glurak": "charizard", "pikachu": "pikachu", "mewtu": "mewtwo",
    "zapdos": "zapdos", "arktos": "articuno", "lavados": "moltres",
    "impergator": "feraligatr", "endivie": "chikorita",
    "karnimani": "totodile", "feurigel": "cyndaquil",
    "rayquaza": "rayquaza", "lugia": "lugia", "hooh": "ho-oh",
    "gengar": "gengar", "alpollo": "clefable", "relaxo": "snorlax",
    "dragoran": "dragonite", "bisaflor": "venusaur", "turtok": "blastoise",
    "zacian": "zacian", "zamazenta": "zamazenta", "calyrex": "calyrex",
    "koraidon": "koraidon", "miraidon": "miraidon", "eevee": "eevee",
    "evoli": "eevee", "sylveon": "sylveon", "feelinara": "sylveon",
}

# Zusätze, die die Produktvariante bestimmen
VARIANT_HINTS = {
    "pokemon center": "pokemon center",
    "pokémon center": "pokemon center",
    "pokemoncenter": "pokemon center",
    "elite": "elite",
}

_PACK_RE = re.compile(r"(\d{1,2})\s*er\b")


def deaccent(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return (s.replace("ß", "ss"))


def norm(s: str) -> str:
    """Kleinschreibung, ohne Umlaute/Sonderzeichen, einfache Leerzeichen."""
    s = deaccent(s).lower()
    s = re.sub(r"[^a-z0-9#]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> set:
    return {t for t in norm(s).split() if len(t) > 1}


def detect_set(article: str):
    """(deutscher Setname, englischer group_name) oder (None, None)."""
    a = norm(article)
    best = None
    for de, en in SET_DE_EN.items():
        d = norm(de)
        if d and d in a and (best is None or len(d) > len(norm(best[0]))):
            best = (de, en)
    return best if best else (None, None)


def detect_type(article: str):
    """(kategorie, englische Kernbegriffe) oder (None, [])."""
    a = norm(article)
    for de, cat, en_terms in TYPE_DE:
        if norm(de) in a:
            return cat, en_terms
    return None, []


def detect_pack_count(article: str):
    """Packungszahl aus '18er'/'36er' oder None."""
    m = _PACK_RE.search(norm(article))
    if not m:
        return None
    n = int(m.group(1))
    return n if 3 <= n <= 40 else None


def translate_extras(article: str) -> set:
    """Restliche bedeutungstragende Tokens ins Englische übersetzen."""
    out = set()
    for t in tokens(article):
        out.add(POKEMON_DE_EN.get(t, t))
    for de, en in VARIANT_HINTS.items():
        if norm(de) in norm(article):
            out.update(en.split())
    return out
