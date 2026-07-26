# -*- coding: utf-8 -*-
"""Marktdaten (Aktienindizes, Gold, Silber, Bitcoin) mit zwei Quellen.

Problem der alten Fassung: ausschließlich die inoffizielle Yahoo-Chart-API,
ohne Cookie/Crumb (bricht periodisch weg) und mit `range=1mo` – nach einem
Ausfall von mehr als einem Monat entstand eine unwiederbringliche Lücke.

Jetzt:
  * `range` konfigurierbar; die Pipeline fordert automatisch mehr Historie an,
    wenn die letzte gespeicherte Beobachtung älter ist.
  * Stooq-CSV als vollwertiger Fallback (stabil, kein Key, lange Historie).
  * Gold/Silber optional als Spot-Reihen (XAUUSD/XAGUSD bei Stooq) statt
    Front-Future – Futures erzeugen Roll-Artefakte in Renditereihen.
  * Jede Reihe trägt ihre Quelle, damit Brüche nachvollziehbar sind.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import time

import requests

USER_AGENT = "PokeIndex-Privat/2.0 (privates Forschungsprojekt)"

YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/"
         "{sym}?range={rng}&interval=1d")
STOOQ = "https://stooq.com/q/d/l/?s={sym}&i=d"

# Reihenname -> (Yahoo-Symbol, Stooq-Symbol, Hinweis)
SYMBOLS = {
    "SP500":       ("^GSPC",   "^spx",    "Kursindex ohne Dividenden"),
    "DAX":         ("^GDAXI",  "^dax",    "Performanceindex (inkl. Dividenden)"),
    "NASDAQ100":   ("^NDX",    "^ndx",    "Kursindex ohne Dividenden"),
    "EUROSTOXX50": ("^STOXX50E", "^stx50", "Kursindex ohne Dividenden"),
    "MSCIWORLD":   ("URTH",    "urth.us", "iShares MSCI World ETF als Renditeproxy"),
    "GOLD":        ("GC=F",    "xauusd",  "Stooq: Spot; Yahoo: Front-Future"),
    "SILVER":      ("SI=F",    "xagusd",  "Stooq: Spot; Yahoo: Front-Future"),
    "BITCOIN":     ("BTC-USD", "btcusd",  "24/7-Handel, auch an Wochenenden"),
}


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_yahoo(sym: str, rng: str = "3mo", session=None) -> dict:
    s = session or _session()
    url = YAHOO.format(sym=sym.replace("^", "%5E"), rng=rng)
    r = s.get(url, timeout=60)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    closes = ((ind.get("adjclose") or [{}])[0].get("adjclose")
              or (ind.get("quote") or [{}])[0].get("close") or [])
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        out[time.strftime("%Y-%m-%d", time.gmtime(t))] = float(c)
    return out


def fetch_stooq(sym: str, session=None) -> dict:
    s = session or _session()
    r = s.get(STOOQ.format(sym=sym), timeout=60)
    r.raise_for_status()
    text = r.text
    if not text.lower().startswith("date"):
        raise RuntimeError(f"Stooq-Antwort unbrauchbar für {sym}: {text[:60]!r}")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        d, c = row.get("Date"), row.get("Close")
        if not d or not c or c in ("N/D", "-"):
            continue
        try:
            out[d] = float(c)
        except ValueError:
            continue
    return out


def needed_range(last_date: str | None, today: str | None = None) -> str:
    """Yahoo-Range so wählen, dass die Lücke sicher überdeckt wird."""
    if not last_date:
        return "5y"
    today = today or dt.date.today().isoformat()
    gap = (dt.date.fromisoformat(today) - dt.date.fromisoformat(last_date)).days
    if gap <= 20:
        return "1mo"
    if gap <= 80:
        return "3mo"
    if gap <= 300:
        return "1y"
    return "5y"


def fetch_series(name: str, last_date: str | None = None,
                 prefer_spot: bool = True, session=None) -> tuple[dict, str]:
    """(datum->schlusskurs, quelle). Yahoo zuerst, Stooq als Fallback.

    prefer_spot: für Gold/Silber Stooq-Spot vorziehen (keine Roll-Effekte).
    """
    y_sym, s_sym, _note = SYMBOLS[name]
    session = session or _session()
    order = ["stooq", "yahoo"] if (prefer_spot and name in ("GOLD", "SILVER")) \
        else ["yahoo", "stooq"]
    errors = []
    for src in order:
        try:
            if src == "yahoo":
                data = fetch_yahoo(y_sym, needed_range(last_date), session)
            else:
                data = fetch_stooq(s_sym, session)
            if data:
                return data, src
            errors.append(f"{src}: leer")
        except Exception as exc:                        # noqa: BLE001
            errors.append(f"{src}: {exc}")
    raise RuntimeError(f"{name}: keine Quelle lieferte Daten ({'; '.join(errors)})")
