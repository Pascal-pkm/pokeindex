# -*- coding: utf-8 -*-
"""Datenvalidierung – die Pipeline soll laut scheitern, nicht still verfälschen.

Vorher gab es keine einzige Prüfung: ein leerer oder halber Abzug wurde
committet, der Index rechnete darauf weiter, und auffällig wurde es
allenfalls Wochen später im Chart.

Geprüft wird:
  * Lücken in der Tagesreihe (fehlende Kalendertage)
  * Zeilenzahl-Drift gegen die Vortage (Abzug abgebrochen? Quelle kaputt?)
  * Preis-Plausibilität (nicht-positive, absurd hohe Werte)
  * Duplikate je Produkt/Tag
  * Zensur-Rand: wie viele Produkte fallen unter die Speichergrenze
    (Zensur entfernt genau die Verlierer aus dem Universum – ohne
    Gegenmaßnahme entsteht ein Aufwärts-Bias im Index)

`Report.failed` unterscheidet harte Fehler (Abbruch) von Warnungen.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# Harte Grenzen
MAX_PLAUSIBLE_CENTS = 5_000_000        # 50.000 USD je Einzelprodukt
ROWCOUNT_DROP_FAIL = 0.50              # >50 % weniger Zeilen als Median = Fehler
ROWCOUNT_DROP_WARN = 0.25
ROWCOUNT_JUMP_WARN = 0.50


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return bool(self.errors)

    def error(self, msg: str):
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)

    def render(self) -> str:
        out = []
        for k, v in self.info.items():
            out.append(f"  {k}: {v}")
        for w in self.warnings:
            out.append(f"  WARNUNG  {w}")
        for e in self.errors:
            out.append(f"  FEHLER   {e}")
        return "\n".join(out) if out else "  (keine Auffälligkeiten)"


def check_date_gaps(dates: list, rep: Report, label: str = "Tagesreihe",
                    hard: bool = False) -> list:
    """Fehlende Kalendertage zwischen erster und letzter Beobachtung."""
    if not dates:
        rep.error(f"{label}: keine Daten vorhanden")
        return []
    have = {dt.date.fromisoformat(d) for d in dates}
    start, end = min(have), max(have)
    missing = []
    d = start
    while d <= end:
        if d not in have:
            missing.append(d.isoformat())
        d += dt.timedelta(days=1)
    rep.info[f"{label}"] = f"{len(dates)} Tage, {start} bis {end}, {len(missing)} Lücken"
    if missing:
        msg = (f"{label}: {len(missing)} fehlende Tage "
               f"(erste: {', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''})")
        rep.error(msg) if hard else rep.warn(msg)
    return missing


def check_rowcount(counts: dict, rep: Report, label: str = "Tagesdatei") -> None:
    """counts: {datum: zeilen}. Vergleicht den jüngsten Tag mit dem Median
    der 10 vorangehenden Tage."""
    if len(counts) < 3:
        return
    days = sorted(counts)
    last = days[-1]
    ref = [counts[d] for d in days[-11:-1]]
    if not ref:
        return
    ref_sorted = sorted(ref)
    med = ref_sorted[len(ref_sorted) // 2]
    if med <= 0:
        return
    ratio = counts[last] / med
    rep.info[f"{label} {last}"] = f"{counts[last]} Zeilen (Median Vortage {med}, {ratio:.2f}x)"
    if ratio < 1 - ROWCOUNT_DROP_FAIL:
        rep.error(f"{label} {last}: nur {counts[last]} Zeilen gegen Median {med} "
                  f"({ratio:.0%}) – Abzug vermutlich abgebrochen")
    elif ratio < 1 - ROWCOUNT_DROP_WARN:
        rep.warn(f"{label} {last}: {counts[last]} Zeilen gegen Median {med} ({ratio:.0%})")
    elif ratio > 1 + ROWCOUNT_JUMP_WARN:
        rep.warn(f"{label} {last}: Zeilensprung nach oben ({ratio:.2f}x) – "
                 f"Set-Universum erweitert?")


def check_prices(rows, rep: Report, label: str = "Preise") -> None:
    """rows: Iterable von (product_id, cents, sub_type)."""
    seen = set()
    dupes = nonpos = absurd = 0
    n = 0
    for pid, cents, _sub in rows:
        n += 1
        if pid in seen:
            dupes += 1
        seen.add(pid)
        if cents is None or cents <= 0:
            nonpos += 1
        elif cents > MAX_PLAUSIBLE_CENTS:
            absurd += 1
    rep.info[label] = f"{n} Zeilen, {len(seen)} Produkte"
    if dupes:
        rep.error(f"{label}: {dupes} doppelte Produkt-IDs am selben Tag")
    if nonpos:
        rep.error(f"{label}: {nonpos} nicht-positive Preise")
    if absurd:
        rep.warn(f"{label}: {absurd} Preise über {MAX_PLAUSIBLE_CENTS/100:,.0f} USD "
                 f"(Platzhalter-Listings?)")


def censoring_report(per_product: dict, dates: list, min_cents: int,
                     keep_cents: int, rep: Report) -> dict:
    """Wie stark wirkt die Speicher-Untergrenze?

    Zählt Produkte, die zwischen `keep_cents` und `min_cents` liegen (also nur
    dank Hysterese noch erfasst werden) sowie Reihen, die nach einer Lücke
    wieder auftauchen. Beides quantifiziert den Zensur-Bias.
    """
    n = len(dates)
    if n < 2:
        return {}
    last_di = n - 1
    in_band = reentries = 0
    for _pid, raw in per_product.items():
        v = raw.get(last_di)
        if v is not None and keep_cents <= v < min_cents:
            in_band += 1
        seen = sorted(raw)
        for a, b in zip(seen, seen[1:]):
            if b - a > 1:
                reentries += 1
                break
    out = {"produkte_in_hysterese_band": in_band, "reihen_mit_luecken": reentries}
    rep.info["Zensur"] = (f"{in_band} Produkte im Halteband "
                          f"({keep_cents/100:.0f}–{min_cents/100:.0f} USD), "
                          f"{reentries} Reihen mit Lücken")
    return out


def check_index_result(res: dict, rep: Report, name: str) -> None:
    """Plausibilität eines fertigen Indexergebnisses."""
    if not res:
        rep.error(f"{name}: kein Ergebnis")
        return
    ov = res["overview"]
    diag = res.get("diagnostics", {})
    rep.info[name] = (f"Stand {res['asof']}, Level {ov['level']}, "
                      f"{len(res['rows'])} Mitglieder, "
                      f"Carry-Anteil {diag.get('carried_share_last')}")
    if ov["level"] <= 0:
        rep.error(f"{name}: Indexniveau <= 0")
    if ov.get("prev"):
        chg = abs(ov["level"] / ov["prev"] - 1)
        if chg > 0.15:
            rep.error(f"{name}: Tagesänderung {chg:.1%} – unplausibel, Datenfehler?")
        elif chg > 0.07:
            rep.warn(f"{name}: Tagesänderung {chg:.1%}")
    if diag.get("days_without_breadth"):
        rep.warn(f"{name}: {diag['days_without_breadth']} Tage ohne ausreichende "
                 f"Marktbreite (Niveau gehalten)")
    share = diag.get("carried_share_last")
    if share is not None and share > 0.5:
        rep.warn(f"{name}: {share:.0%} der Mitglieder mit fortgeschriebenem Preis")
