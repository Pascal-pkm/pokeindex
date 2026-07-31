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


def brotli_verfuegbar() -> bool:
    """True, wenn urllib3 Brotli entpacken kann.

    Es gibt zwei Pakete, die das leisten: `brotli` und `brotlicffi`. urllib3
    akzeptiert beide, also prüfen wir auch beide.
    """
    for modul in ("brotli", "brotlicffi"):
        try:
            __import__(modul)
            return True
        except ImportError:
            continue
    return False


def diagnose() -> str:
    """Vollständige Umgebungs- und Verbindungsdiagnose als Text.

    Wird bei einem Fehlschlag automatisch ausgegeben, damit im Log steht,
    WORAN es lag – statt nur "exit code 1".
    """
    import platform
    zeilen = [
        f"Python              {platform.python_version()} auf {platform.system()}",
        f"requests            {requests.__version__}",
    ]
    try:
        import urllib3
        zeilen.append(f"urllib3             {urllib3.__version__}")
    except Exception:                                     # noqa: BLE001
        zeilen.append("urllib3             nicht ermittelbar")
    for modul in ("brotli", "brotlicffi"):
        try:
            m = __import__(modul)
            ver = getattr(m, "__version__", "(ohne Versionsangabe)")
            zeilen.append(f"{modul:<19} {ver}")
        except ImportError:
            zeilen.append(f"{modul:<19} NICHT installiert")
    zeilen.append(f"Brotli nutzbar      {'ja' if brotli_verfuegbar() else 'NEIN'}")
    try:
        r = requests.get(API, headers={"User-Agent": USER_AGENT,
                                       "Accept-Encoding": "br",
                                       "Accept": "application/json"},
                         timeout=60)
        zeilen.append(f"HTTP-Status         {r.status_code}")
        zeilen.append(f"Content-Encoding    {r.headers.get('Content-Encoding', '(keins)')}")
        zeilen.append(f"Content-Type        {r.headers.get('Content-Type', '-')}")
        zeilen.append(f"Antwortgröße        {len(r.content):,} Bytes".replace(",", "."))
        if r.status_code == 200:
            zeilen.append(f"Items               {len(r.json()):,}".replace(",", "."))
        else:
            zeilen.append(f"Antwortanfang       {r.text[:200]!r}")
        for kopf in ("Retry-After", "X-RateLimit-Remaining", "X-RateLimit-Reset",
                     "CF-Ray", "Server"):
            if kopf in r.headers:
                zeilen.append(f"{kopf:<19} {r.headers[kopf]}")
    except Exception as exc:                              # noqa: BLE001
        zeilen.append(f"Verbindungsfehler   {type(exc).__name__}: {exc}")
    return "\n".join("  " + z for z in zeilen)


def _pruefe_brotli() -> None:
    """Brotli ist bei Skinport PFLICHT, nicht optional.

    Nachgemessen am 26.07.2026 gegen die Live-API:
        Accept-Encoding: gzip        -> HTTP 406 Not Acceptable
        Accept-Encoding: br          -> HTTP 200, 25.115 Items
        Accept-Encoding: br, gzip    -> HTTP 200, 25.115 Items
    Ein Rückfall auf gzip (so war es hier kurzzeitig implementiert) führt also
    NICHT zu mehr Datenvolumen, sondern zu einem garantierten Fehlschlag.
    Deshalb hier ein klarer Abbruch statt einer kryptischen 406-Meldung.
    """
    if brotli_verfuegbar():
        return
    raise RuntimeError(
        "Weder 'brotli' noch 'brotlicffi' ist installiert. Die Skinport-API "
        "lehnt Anfragen ohne Brotli-Unterstützung mit HTTP 406 ab.\n"
        "  Installieren:  pip install brotli\n"
        "  Schlägt das auf sehr neuen Python-Versionen fehl (kein Wheel), "
        "läuft der CS2-Abruf nur über GitHub Actions (Python 3.12.7).")


MAX_WARTEN_S = 300      # länger als 5 Minuten wird nicht im Lauf gewartet


def fetch_items(timeout: int = 120, tries: int = 4) -> tuple[list, str]:
    """(items, datenstand_iso) – mit Wiederholungen.

    Rate-Limit: Skinport erlaubt 8 Anfragen je 5 Minuten. Wird das überschritten,
    sperrt Cloudflare deutlich länger und nennt die Dauer im Header
    `Retry-After` – gemessen wurden 2401 Sekunden (40 Minuten). Ein Warten im
    laufenden Workflow ist dann sinnlos; stattdessen wird sauber abgebrochen und
    ein späterer Lauf holt den Tag nach (Workflow cs2.yml läuft alle 3 Stunden).

    Wichtig zur Fehlersuche: GitHub-Runner teilen sich IP-Bereiche mit vielen
    anderen Nutzern. Das Rate-Limit kann deshalb auch dann greifen, wenn dieses
    Projekt nur eine einzige Anfrage am Tag stellt.
    """
    _pruefe_brotli()
    r = None
    for versuch in range(tries):
        try:
            r = requests.get(API, headers={"User-Agent": USER_AGENT,
                                           "Accept-Encoding": "br",
                                           "Accept": "application/json"},
                             timeout=timeout)
            if r.status_code == 406:
                raise RuntimeError(
                    "HTTP 406 – Skinport verlangt Brotli-Kompression. "
                    "Ist 'brotli' wirklich installiert?")
            if r.status_code == 429:
                warten = r.headers.get("Retry-After")
                try:
                    warten_s = int(warten) if warten else None
                except ValueError:
                    warten_s = None
                if warten_s and warten_s > MAX_WARTEN_S:
                    raise RuntimeError(
                        f"Rate-Limit aktiv, Sperre noch {warten_s // 60} Minuten "
                        f"(Retry-After: {warten_s}s). Kein Warten im Lauf – "
                        f"der nächste geplante CS2-Lauf holt den Tag nach.")
                raise RuntimeError("HTTP 429 (Rate-Limit)")
            if r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            break
        except Exception as exc:                          # noqa: BLE001
            if versuch == tries - 1:
                raise RuntimeError(
                    f"Skinport nicht erreichbar nach {tries} Versuchen: {exc}"
                ) from exc
            # Rate-Limit braucht eine echte Pause (Fenster: 5 Minuten),
            # ein Netz-/Serverfehler nur einen kurzen Moment.
            # Bei dauerhafter Sperre nicht weiter versuchen.
            if "Sperre noch" in str(exc):
                raise
            ist_ratelimit = "429" in str(exc) or "Rate-Limit" in str(exc)
            wartezeit = (90 * (versuch + 1)) if ist_ratelimit else (15 * (versuch + 1))
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
