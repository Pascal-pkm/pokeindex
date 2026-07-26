# -*- coding: utf-8 -*-
"""tcgcsv.com – TCGplayer-Marktpreise (Live-Tagesabzug + Preisarchiv).

Vorher gab es zwei abweichende Implementierungen (Website-Pipeline und
Sealed-Dashboard). Diese ist die einzige.

Referenzpreis: `marketPrice` des wertvollsten REGULÄREN Printings. Ausschlüsse
und Begründungen:
  * "1st Edition" – anderes Gut, extreme Preise, verzerrt die Vergleichbarkeit
  * `highPrice` wird nie verwendet ("price parking": Verkäufer parken absurde
    Preise, um Listings zu halten)

Printing-Stabilität (neu): Wechselt das wertvollste Printing eines Produkts von
Tag zu Tag, vergleicht eine naive Rendite zwei verschiedene Güter. `prefer_sub`
hält deshalb das Printing des Vortags, solange es einen Marktpreis hat, und
wechselt erst, wenn es dauerhaft verschwindet.
"""
from __future__ import annotations

import time

import requests

BASE_URL = "https://tcgcsv.com/tcgplayer"
ARCHIVE_URL = "https://tcgcsv.com/archive/tcgplayer/prices-{d}.ppmd.7z"
ARCHIVE_START = "2024-02-08"          # frühester Tag im tcgcsv-Archiv
LAST_UPDATED = "https://tcgcsv.com/last-updated.txt"
CATEGORY_POKEMON = 3
USER_AGENT = "PokeIndex-Privat/2.0 (privates Forschungsprojekt)"

EXCLUDED_SUBTYPES = ("1st edition",)


class TcgCsv:
    def __init__(self, category: int = CATEGORY_POKEMON, pause: float = 0.25):
        self.category = category
        self.pause = pause
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT})

    def _get_json(self, url: str, tries: int = 4):
        last = None
        for i in range(tries):
            try:
                r = self.s.get(url, timeout=60)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as exc:
                last = exc
                if i == tries - 1:
                    break
                time.sleep(3 * (i + 1))
        raise RuntimeError(f"tcgcsv-Abruf fehlgeschlagen: {url} ({last})")

    def official_date(self) -> str:
        """Datenstand der Quelle (nicht die lokale Uhr!)."""
        r = self.s.get(LAST_UPDATED, timeout=30)
        r.raise_for_status()
        return r.text.strip()[:10]

    def groups(self) -> list:
        data = self._get_json(f"{BASE_URL}/{self.category}/groups")
        return (data or {}).get("results", [])

    def products(self, group_id) -> list:
        data = self._get_json(f"{BASE_URL}/{self.category}/{group_id}/products")
        time.sleep(self.pause)
        return (data or {}).get("results", [])

    def prices(self, group_id) -> list:
        data = self._get_json(f"{BASE_URL}/{self.category}/{group_id}/prices")
        time.sleep(self.pause)
        return (data or {}).get("results", [])


def choose_price(price_rows, prefer_sub: str | None = None):
    """(marketPrice, subTypeName) des wertvollsten regulären Printings.

    `prefer_sub`: Printing des Vortags. Existiert dafür ein Marktpreis, wird es
    beibehalten – das verhindert künstliche Renditen durch Printing-Wechsel.
    """
    best = None
    preferred = None
    for p in price_rows:
        sub = p.get("subTypeName") or ""
        if any(x in sub.lower() for x in EXCLUDED_SUBTYPES):
            continue
        m = p.get("marketPrice")
        if m is None:
            continue
        if prefer_sub and sub == prefer_sub:
            preferred = (m, sub)
        if best is None or m > best[0]:
            best = (m, sub)
    return preferred or best
