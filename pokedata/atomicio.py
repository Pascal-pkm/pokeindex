# -*- coding: utf-8 -*-
"""Atomare Schreibvorgänge.

Warum: Die Pipeline schrieb Tagesdateien, Stammdaten und JS-Artefakte direkt
an den Zielpfad. Bricht der Prozess mitten im Schreiben ab (Actions-Timeout,
Netzabbruch, Strg-C), bleibt eine halbe Gzip-Datei liegen – die Indexhistorie
wird dadurch dauerhaft falsch, ohne dass jemand es merkt.

Alle Schreiber hier erzeugen erst eine temporäre Datei im Zielverzeichnis und
verschieben sie per os.replace() (atomar auf einem Dateisystem). Ergebnis:
entweder der alte oder der neue Inhalt, nie ein Mischzustand.
"""
from __future__ import annotations

import contextlib
import csv
import gzip
import io
import json
import os
import tempfile
from contextlib import contextmanager


@contextmanager
def atomic_path(path: str, suffix: str = ".tmp"):
    """Liefert einen temporären Pfad, der am Ende auf `path` verschoben wird."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pd_", suffix=suffix)
    os.close(fd)
    try:
        yield tmp
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)
        raise


def write_text(path: str, text: str, encoding: str = "utf-8",
               bom: bool = False) -> None:
    """Text atomar schreiben.

    bom=True für Dateien, die der Nutzer in Excel oder Windows PowerShell
    öffnet: beide interpretieren UTF-8 ohne Byte-Order-Mark als ANSI und
    zerstören damit alle Umlaute ("Weiße Flammen" -> "WeiÃŸe Flammen").
    """
    enc = "utf-8-sig" if (bom and encoding == "utf-8") else encoding
    with atomic_path(path) as tmp, open(tmp, "w", encoding=enc, newline="") as f:
        f.write(text)


def write_bytes(path: str, data: bytes) -> None:
    with atomic_path(path) as tmp, open(tmp, "wb") as f:
        f.write(data)


def write_gzip_text(path: str, text: str, encoding: str = "utf-8") -> None:
    # mtime=0 UND filename="" -> byte-identische Ausgabe bei gleichem Inhalt.
    # Ohne filename="" schreibt GzipFile den (zufälligen) Namen der
    # Temporärdatei in den Header; die Datei wäre bei jedem Lauf anders und git
    # würde Änderungen ohne inhaltlichen Unterschied committen.
    with atomic_path(path) as tmp, open(tmp, "wb") as fh, gzip.GzipFile(
            filename="", mode="wb", fileobj=fh, compresslevel=9, mtime=0) as gz:
        gz.write(text.encode(encoding))


def write_gzip_csv(path: str, header, rows) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if header:
        w.writerow(header)
    for r in rows:
        w.writerow(r)
    write_gzip_text(path, buf.getvalue())


def write_gzip_dictcsv(path: str, fieldnames, rows) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n",
                       extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    write_gzip_text(path, buf.getvalue())


def write_csv(path: str, header, rows, bom: bool = False) -> None:
    """CSV atomar schreiben. bom=True für Dateien, die in Excel geöffnet werden."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n" if bom else "\n")
    if header:
        w.writerow(header)
    for r in rows:
        w.writerow(r)
    write_text(path, buf.getvalue(), bom=bom)


def write_json(path: str, obj, indent: int | None = 1) -> None:
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=indent))


def write_js_var(path: str, varname: str, obj, epilogue: str = "") -> None:
    """`window.<varname>=<json>;` – das Ladeformat der statischen Website."""
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    write_text(path, f"window.{varname}={payload};{epilogue}")


def read_js_var(path: str):
    """Gegenstück zu write_js_var: liest `window.X=<json>;` zurück."""
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    start = txt.index("=") + 1
    end = txt.rindex(";")
    # Falls ein Epilog angehängt wurde, endet das JSON vor dem ersten ';document'
    cut = txt.find(";document", start)
    if cut != -1:
        end = cut
    return json.loads(txt[start:end])
