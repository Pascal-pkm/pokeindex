# -*- coding: utf-8 -*-
"""Skinport-API (CS2-Items) – öffentlich, ohne Login.

Preisdefinition und ihre Grenze (vorher nur im README, jetzt im Datenmodell):
`median_price` ist der Median der AKTUELLEN ANGEBOTE (Ask), nicht ein
Transaktionspreis. Er liegt strukturell über dem realisierbaren Verkaufspreis.
Die Steam-Vorgeschichte dagegen besteht aus tatsächlichen Verkäufen.
Deshalb trägt jeder Abzug ein `price_kind`-Feld ("ask"), und die Verkettung im
Index vermerkt den Quellenbruch ausdrücklich.

Zusätzlich wird das Datum aus dem HTTP-`Date`-Header der Antwort abgeleitet
(Serverzeit der Quelle) statt aus der lokalen Uhr des Runners.
"""
from __future__ import annotations

import datetime as dt
import email.utils

import requests

API = "https://api.skinport.com/v1/items?app_id=730&currency=USD"
USER_AGENT = "PokeIndex-Privat/2.0 (privates Forschungsprojekt)"
PRICE_KIND = "ask"          # median der Listings, kein Verkaufspreis


def _accept_encoding() -> str:
    """Brotli nur anfordern, wenn es entpackt werden kann.

    Die Skinport-API antwortet gern Brotli-komprimiert. Ist das Paket `brotli`
    nicht installiert (auf sehr neuen Python-Versionen fehlt dafür noch ein
    Wheel), kann requests die Antwort nicht lesen. Dann wird nur gzip
    angefordert – funktional identisch, geringfügig mehr Datenvolumen.
    """
    try:
        import brotli  # noqa: F401
        return "br, gzip"
    except ImportError:
        return "gzip"


def fetch_items(timeout: int = 120) -> tuple[list, str]:
    """(items, datenstand_iso)."""
    r = requests.get(API, headers={"User-Agent": USER_AGENT,
                                   "Accept-Encoding": _accept_encoding()},
                     timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError("Unerwartete Skinport-Antwort (keine Liste)")
    stamp = r.headers.get("Date")
    if stamp:
        try:
            datum = email.utils.parsedate_to_datetime(stamp).date().isoformat()
        except (TypeError, ValueError):
            datum = dt.datetime.now(dt.timezone.utc).date().isoformat()
    else:
        datum = dt.datetime.now(dt.timezone.utc).date().isoformat()
    return data, datum


def normalize(items) -> list:
    """[(market_hash_name, cents, quantity, created_at)] mit Plausibilitätsfilter."""
    out = []
    for it in items:
        name = it.get("market_hash_name")
        price = it.get("median_price")
        if price is None:
            price = it.get("min_price")
        if not name or price is None:
            continue
        try:
            cents = round(float(price) * 100)
        except (TypeError, ValueError):
            continue
        if cents <= 0:
            continue
        out.append((name, cents, int(it.get("quantity") or 0),
                    str(it.get("created_at") or "")))
    return out
