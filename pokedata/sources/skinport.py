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
import time

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


def fetch_items(timeout: int = 120, tries: int = 4) -> tuple[list, str]:
    """(items, datenstand_iso) – mit Wiederholungen.

    Die Skinport-API ist zeitweise nicht erreichbar oder antwortet mit 429/5xx
    (Rate-Limit: 8 Anfragen je 5 Minuten). Ein einzelner Fehlversuch hat die
    CS2-Reihe früher für einen ganzen Tag ausfallen lassen – bei täglicher
    Erhebung entsteht daraus sofort eine Lücke. Deshalb mehrere Versuche mit
    wachsender Wartezeit.
    """
    r = None
    for versuch in range(tries):
        try:
            r = requests.get(API, headers={"User-Agent": USER_AGENT,
                                           "Accept-Encoding": _accept_encoding()},
                             timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            break
        except Exception as exc:                          # noqa: BLE001
            if versuch == tries - 1:
                raise RuntimeError(
                    f"Skinport nicht erreichbar nach {tries} Versuchen: {exc}"
                ) from exc
            wartezeit = 20 * (versuch + 1)
            print(f"  Skinport-Abruf fehlgeschlagen ({exc}) – "
                  f"warte {wartezeit}s und versuche erneut ...")
            time.sleep(wartezeit)
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
