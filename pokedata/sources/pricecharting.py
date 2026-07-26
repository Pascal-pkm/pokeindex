# -*- coding: utf-8 -*-
"""PriceCharting – Bestandsscraper für Karten und Sealed-Produkte.

Gemeinsame Basis der beiden Wurzel-Skripte (karten_scraper.py,
sealed_scraper.py), die vorher denselben Code in zwei divergierenden Fassungen
enthielten – inklusive eines Bugs, der nur in einer der beiden gefixt war:

  * Discovery über Set-Seiten: die Kartenfassung parste das JSON der API mit
    einem Regex auf escapte Anführungszeichen (brach bei jeder Formatänderung),
    die Sealed-Fassung nutzte korrekt json.loads + Cursor. Hier gilt die
    korrekte Variante für beide.
  * Sealed-Erkennung ohne Wortgrenzen (karten) vs. mit (sealed): jetzt
    einheitlich über pokedata.classify.
  * `datetime.utcfromtimestamp` ist ab Python 3.12 deprecated – ersetzt durch
    zeitzonenbewusste Umrechnung.

Erhebungsethik: Live-Abruf mit Verzögerung, 429-Backoff, ehrlicher
User-Agent; alternativ Snapshots des Internet Archive (`wayback=True`), die
für die wissenschaftliche Verwertung die konservativere Quelle sind.
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import re
import sqlite3
import time
import urllib.parse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .. import classify

CDX = "https://web.archive.org/cdx/search/cdx"
CATEGORY_URL = "https://www.pricecharting.com/category/pokemon-cards"
CONSOLE_JSON = ("https://www.pricecharting.com/console/%s"
                "?sort=name&cursor=%d&format=json")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "masterarbeit-research/2.0"),
      "Accept-Encoding": "gzip"}

CHART_RE = re.compile(r"VGPC\.chart_data\s*=\s*(\{.*?\});", re.S)
NAME_RE = re.compile(r'<h1[^>]*id="product_name"[^>]*>\s*([^<]+?)\s*<', re.S)
GAME_URL_RE = re.compile(
    r"https://www\.pricecharting\.com/game/(pokemon-[^/]+)/([^/]+)$")

# PriceCharting-Grade-Schlüssel -> sprechende Bezeichnung
CARD_GRADES = {"used": "Ungraded (Raw)", "graded": "Grade 9",
               "manualonly": "PSA 10", "new": "Neu/Sealed",
               "cib": "CIB", "boxonly": "Nur Box"}


def fetch(url: str, timeout: int = 60, tries: int = 3) -> str | None:
    """HTTP-GET mit Gzip, Wiederholungen und 429-Backoff."""
    for attempt in range(tries):
        try:
            with urlopen(Request(url, headers=UA), timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return raw.decode("utf-8", "replace")
        except HTTPError as exc:
            if exc.code in (404, 410):
                return None
            if exc.code == 429:
                wait = 60 * (attempt + 1)
                print(f"    Rate-Limit (429) – warte {wait}s ...")
                time.sleep(wait)
                continue
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
        except URLError:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    return None


def parse_chart(html: str) -> dict:
    """VGPC.chart_data -> {grade: [(JJJJ-MM-TT, preis_usd), ...]}"""
    m = CHART_RE.search(html or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    out = {}
    for grade, points in data.items():
        serie = []
        for p in points:
            try:
                ts_ms, cents = p[0], p[1]
            except (TypeError, IndexError):
                continue
            if not cents or cents <= 0:
                continue
            day = dt.datetime.fromtimestamp(ts_ms / 1000, dt.timezone.utc).date()
            serie.append((day.isoformat(), cents / 100.0))
        if serie:
            out[grade] = serie
    return out


def parse_name(html: str) -> str | None:
    m = NAME_RE.search(html or "")
    if not m:
        return None
    import html as html_mod
    return re.sub(r"\s+", " ", html_mod.unescape(m.group(1))).strip()


# ------------------------------------------------------------------ Discovery
def discover_cdx(want_sealed: bool, from_year: str = "2020") -> list:
    """Produkt-URLs über den CDX-Index des Internet Archive (ein Request).

    Grenze, die dokumentiert sein muss: erfasst nur je archivierte Seiten.
    Nie archivierte (neue, unpopuläre) Produkte fehlen systematisch – deshalb
    ergänzt `discover_live` die Liste.
    """
    query = urllib.parse.urlencode({
        "url": "pricecharting.com/game/pokemon", "matchType": "prefix",
        "output": "json", "collapse": "urlkey", "fl": "original",
        "filter": "statuscode:200", "from": from_year, "limit": "300000"})
    text = fetch(f"{CDX}?{query}", timeout=180)
    lines = json.loads(text)[1:] if text and text.strip() else []
    urls = set()
    for row in lines:
        u = row[0].split("?")[0].replace("http://", "https://").replace(":80/", "/")
        m = GAME_URL_RE.match(u)
        if not m:
            continue
        if classify.looks_sealed_slug(m.group(2)) == want_sealed:
            urls.add(u)
    return sorted(urls)


def discover_live(want_sealed: bool, pause: float = 1.0,
                  progress=print) -> list:
    """Set-Seiten über die JSON-API durchblättern (products[].productUri)."""
    html = fetch(CATEGORY_URL) or ""
    sets = sorted(set(re.findall(r'href="/console/(pokemon-[^"/?]+)"', html)))
    progress(f"  {len(sets)} Sets gefunden")
    urls = set()
    for i, slug in enumerate(sets, 1):
        cursor = 0
        while True:
            page = fetch(CONSOLE_JSON % (slug, cursor))
            if not page:
                break
            try:
                data = json.loads(page)
            except json.JSONDecodeError:
                break
            prods = data.get("products") or []
            if not prods:
                break
            for p in prods:
                puri = p.get("productUri") or ""
                curi = p.get("consoleUri") or slug
                if not puri:
                    continue
                if classify.looks_sealed_slug(puri) == want_sealed:
                    urls.add(f"https://www.pricecharting.com/game/{curi}/{puri}")
            try:
                nxt = int(data.get("cursor") or 0)
            except (TypeError, ValueError):
                break
            if nxt <= cursor:
                break
            cursor = nxt
            time.sleep(pause)
        if i % 25 == 0:
            progress(f"  ... {i}/{len(sets)} Sets, bisher {len(urls)} Produkte")
        time.sleep(pause)
    return sorted(urls)


def wayback_snapshot_url(url: str) -> str | None:
    """Jüngsten Archive-Snapshot einer URL ermitteln."""
    query = urllib.parse.urlencode({"url": url, "output": "json",
                                    "fl": "timestamp",
                                    "filter": "statuscode:200", "limit": "-1"})
    text = fetch(f"{CDX}?{query}", timeout=60)
    rows = json.loads(text)[1:] if text and text.strip() else []
    if not rows:
        return None
    return f"https://web.archive.org/web/{rows[-1][0]}id_/{url}"


# ------------------------------------------------------------------ Datenbank
def open_db(path: str, kind: str) -> sqlite3.Connection:
    """kind: 'karten' oder 'sealed'. WAL für robustere Schreibvorgänge."""
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=NORMAL")
    if kind == "karten":
        con.executescript("""
        CREATE TABLE IF NOT EXISTS karten(
            id INTEGER PRIMARY KEY,
            url TEXT UNIQUE NOT NULL,
            set_slug TEXT, name TEXT,
            last_fetch TEXT, quelle TEXT);
        CREATE TABLE IF NOT EXISTS kartenpreise(
            karte_id INTEGER NOT NULL,
            grade TEXT NOT NULL,
            datum TEXT NOT NULL,
            preis REAL NOT NULL,
            PRIMARY KEY (karte_id, grade, datum));
        CREATE INDEX IF NOT EXISTS ix_kp_grade ON kartenpreise(grade, datum);
        CREATE INDEX IF NOT EXISTS ix_kp_datum ON kartenpreise(datum);
        """)
    else:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS produkte(
            id INTEGER PRIMARY KEY,
            url TEXT UNIQUE NOT NULL,
            set_slug TEXT, name TEXT, kategorie TEXT,
            last_fetch TEXT, quelle TEXT);
        CREATE TABLE IF NOT EXISTS produktpreise(
            produkt_id INTEGER NOT NULL,
            grade TEXT NOT NULL,
            datum TEXT NOT NULL,
            preis REAL NOT NULL,
            PRIMARY KEY (produkt_id, grade, datum));
        CREATE INDEX IF NOT EXISTS ix_pp_grade ON produktpreise(grade, datum);
        CREATE INDEX IF NOT EXISTS ix_pp_datum ON produktpreise(datum);
        """)
    return con


def scrape(con: sqlite3.Connection, kind: str, delay: float = 2.0,
           limit: int = 0, max_age: int = 0, wayback: bool = False,
           sets_filter: str = "", discover: bool = False,
           discover_live_too: bool = False, log=print) -> dict:
    """Hauptlauf: entdecken (optional), laden, speichern. Resümierbar."""
    is_cards = kind == "karten"
    table = "karten" if is_cards else "produkte"
    ptable = "kartenpreise" if is_cards else "produktpreise"
    idcol = "karte_id" if is_cards else "produkt_id"

    known = {u for (u,) in con.execute(f"SELECT url FROM {table}")}
    if discover or not known:
        log("Entdecke Produkt-URLs (Internet Archive CDX) ...")
        urls = set(discover_cdx(want_sealed=not is_cards))
        log(f"  {len(urls)} URLs über CDX")
        if discover_live_too:
            log("Entdecke zusätzlich über Set-Seiten (live) ...")
            urls |= set(discover_live(want_sealed=not is_cards, progress=log))
        new = urls - known
        for u in sorted(new):
            m = GAME_URL_RE.match(u)
            set_slug = (m.group(1)[len("pokemon-"):] if m else "")
            slug = m.group(2) if m else u
            if is_cards:
                con.execute(f"INSERT OR IGNORE INTO {table}(url, set_slug, name) "
                            f"VALUES (?,?,?)",
                            (u, set_slug, slug.replace("-", " ")))
            else:
                con.execute(f"INSERT OR IGNORE INTO {table}"
                            f"(url, set_slug, name, kategorie) VALUES (?,?,?,?)",
                            (u, set_slug, slug.replace("-", " "),
                             classify.sealed_category_from_slug(slug)))
        con.commit()
        log(f"Neu in Datenbank: {len(new)} (gesamt {len(known | urls)})")

    wanted = [s.strip() for s in sets_filter.split(",") if s.strip()]
    today = dt.date.today()
    todo = []
    for pid, url, set_slug, last in con.execute(
            f"SELECT id, url, set_slug, last_fetch FROM {table}"):
        if wanted and set_slug not in wanted:
            continue
        if max_age and last and \
                (today - dt.date.fromisoformat(last[:10])).days < max_age:
            continue
        todo.append((pid, url))
    if limit:
        todo = todo[:limit]
    log(f"Zu laden: {len(todo)} Produkte (Quelle: "
        f"{'Internet Archive' if wayback else 'pricecharting.com live'}) – "
        f"geschätzt {len(todo) * (delay + 0.8) / 3600:.1f} h")

    ok = miss = 0
    grade_stats: dict = {}
    t0 = time.time()
    for n, (pid, url) in enumerate(todo, 1):
        try:
            target = wayback_snapshot_url(url) if wayback else url
            html = fetch(target) if target else None
            chart = parse_chart(html) if html else {}
            if chart:
                name = parse_name(html)
                if name:
                    con.execute(f"UPDATE {table} SET name=? WHERE id=?", (name, pid))
                for grade, serie in chart.items():
                    grade_stats[grade] = grade_stats.get(grade, 0) + 1
                    con.executemany(
                        f"INSERT OR REPLACE INTO {ptable}"
                        f"({idcol}, grade, datum, preis) VALUES (?,?,?,?)",
                        [(pid, grade, d, p) for d, p in serie])
                ok += 1
            else:
                miss += 1
            con.execute(f"UPDATE {table} SET last_fetch=?, quelle=? WHERE id=?",
                        (today.isoformat(), "wayback" if wayback else "live", pid))
            if n % 25 == 0:
                con.commit()
                rate = n / max(time.time() - t0, 1)
                log(f"  {n}/{len(todo)} (ok {ok}, leer/Fehler {miss}) – "
                    f"Rest ~{(len(todo) - n) / rate / 3600:.1f} h")
        except KeyboardInterrupt:
            log("Abbruch – Fortschritt ist gespeichert, einfach erneut starten.")
            break
        except Exception as exc:                          # noqa: BLE001
            miss += 1
            log(f"  Fehler bei {url}: {exc}")
        time.sleep(delay)
    con.commit()
    return {"ok": ok, "leer": miss, "grades": grade_stats,
            "preispunkte": con.execute(f"SELECT COUNT(*) FROM {ptable}").fetchone()[0]}
