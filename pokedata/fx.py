# -*- coding: utf-8 -*-
"""EZB-Tagesreferenzkurse (USD/EUR) über frankfurter.dev – kostenlos, kein Key.

Der Kurs wird lokal als CSV zwischengespeichert (`data/fx_usd_eur.csv`), damit
Auswertungen offline reproduzierbar sind und die API nicht bei jedem Lauf für
die komplette Historie befragt wird.

Wochenenden/Feiertage haben keinen Referenzkurs; sie werden aus dem letzten
Handelstag fortgeschrieben (Forward-Fill), begrenzt auf `MAX_FFILL_DAYS`.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import urllib.request

from .atomicio import write_csv

API = "https://api.frankfurter.dev/v1/{start}..{end}?base=USD&symbols=EUR"
MAX_FFILL_DAYS = 7
USER_AGENT = "PokeIndex-Privat/2.0 (privates Forschungsprojekt)"


def _fetch(start: str, end: str) -> dict:
    url = API.format(start=start, end=end)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {d: float(v["EUR"]) for d, v in (data.get("rates") or {}).items()
            if v.get("EUR")}


def load_cache(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                out[row["date"]] = float(row["usd_eur"])
            except (TypeError, ValueError):
                continue
    return out


def save_cache(path: str, rates: dict) -> None:
    write_csv(path, ["date", "usd_eur"],
              [[d, f"{rates[d]:.6f}"] for d in sorted(rates)])


def update(path: str, start: str = "2013-01-01", end: str | None = None,
           offline: bool = False) -> dict:
    """Cache aktualisieren und vollständige Kursreihe zurückgeben."""
    rates = load_cache(path)
    end = end or dt.date.today().isoformat()
    if offline:
        return rates
    have_start = min(rates) if rates else None
    have_end = max(rates) if rates else None
    todo = []
    if not rates:
        todo.append((start, end))
    else:
        if start < have_start:
            todo.append((start, have_start))
        if end > have_end:
            todo.append((have_end, end))
    for s, e in todo:
        try:
            rates.update(_fetch(s, e))
        except Exception as exc:                      # noqa: BLE001
            print(f"  FX {s}..{e}: {exc} – nächster Lauf holt nach")
    if rates:
        save_cache(path, rates)
    return rates


def rate_on(rates: dict, day: str, max_ffill: int = MAX_FFILL_DAYS) -> float | None:
    """Kurs des Tages, sonst letzter Handelstag innerhalb `max_ffill` Tagen."""
    if day in rates:
        return rates[day]
    d = dt.date.fromisoformat(day)
    for back in range(1, max_ffill + 1):
        key = (d - dt.timedelta(days=back)).isoformat()
        if key in rates:
            return rates[key]
    return None


def usd_to_eur(amount_usd: float, day: str, rates: dict) -> float | None:
    r = rate_on(rates, day)
    return None if r is None else amount_usd * r


def eur_to_usd(amount_eur: float, day: str, rates: dict) -> float | None:
    r = rate_on(rates, day)
    return None if not r else amount_eur / r
