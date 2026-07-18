# -*- coding: utf-8 -*-
"""
Newsletter im Stil von "The Daily Spark" (Apollo Global Management):
kurze Eyebrow-Kategorie, eine zugespitzte Schlagzeile, knapper Fließtext mit
einer fett gesetzten Kernaussage, EIN Chart mit Quellenangabe, dezente Tabellen
ohne Kästchen-Optik. Zwei Ausgaben:

  --mode daily   taeglich: Tagesveraenderung aller Indizes, ein 30-Tage-Chart,
                 sehr kompakt (soll in <30 Sekunden lesbar sein)
  --mode weekly  Sonntags-Briefing: Wochenrueckblick je Anlageklasse, Top-
                 Movers, Maerkte-Vergleich, 180-Tage-Chart, ausfuehrlicher

Versand per Gmail-SMTP. Benoetigte Umgebungsvariablen (GitHub-Secrets):
  GMAIL_ADDRESS       Absender-Gmail-Adresse
  GMAIL_APP_PASSWORD  Gmail-App-Passwort (nicht das normale Passwort!)
  NEWSLETTER_TO       Empfaenger, Komma-getrennt (optional, Standard = Absender)

Jede Ausgabe wird zusaetzlich unter site/newsletter/JJJJ-MM-TT-{daily,weekly}.html
archiviert (Chart als eingebettetes Base64-Bild) und in site/data/newsletters.js
gelistet (Archiv auf der Website).

Aufruf:  python scripts/send_newsletter.py --mode daily [--dry-run]
         python scripts/send_newsletter.py --mode weekly [--dry-run]
"""
import argparse
import base64
import datetime as dt
import html
import io
import json
import os
import smtplib
import ssl
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from common import CARD_INDEX, ROOT, SEALED_INDEX, SITE_DATA

NL_DIR = os.path.join(ROOT, "site", "newsletter")
CS2_INDEX = "CS2500"
IDX_FILES = {"SPK500": ("window.IDX_CARDS=", "idx_SPK500.js"),
             "SPKS": ("window.IDX_SEALED=", "idx_SPKS.js"),
             "CS2500": ("window.IDX_CS2=", "idx_CS2.js")}


def load_full_series(idx_name):
    """Volle Historie direkt aus site/data/idx_*.js laden (summary.json haelt
    fuer 'series_tail' nur die letzten 30 Punkte vor, das reicht nicht fuer
    den 180-Tage-Chart im Wochenbriefing)."""
    prefix, fn = IDX_FILES[idx_name]
    path = os.path.join(SITE_DATA, fn)
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    data = json.loads(txt[len(prefix):].rstrip().rstrip(";"))
    return data["series"]


MARKET_NAMES = {"SP500": "S&P 500", "DAX": "DAX", "NASDAQ100": "NASDAQ 100",
                "EUROSTOXX50": "EuroStoxx 50", "MSCIWORLD": "MSCI World",
                "GOLD": "Gold", "SILVER": "Silber", "BITCOIN": "Bitcoin"}
IDX_LABELS = {"SPK500": "Kartenindex (SPK500)", "SPKS": "Sealed-Index (SPKS)",
              "CS2500": "CS2-Skin-Index (CS2500)"}

# --------------------------------------------------------------- Optik/Stil
INK = "#15181d"        # Fliesstext, fast schwarz
SUB = "#6b7280"        # gedaempftes Grau fuer Meta-Text
RULE = "#e7e5e0"       # helle Trennlinie
PAPER = "#fdfcfa"      # leicht warmes Off-White als Hintergrund
SPARK = "#b45309"      # warmes Amber als Akzentfarbe (Eyebrow, Chart-Linie)
UP = "#1a7a42"
DOWN = "#c22b2b"
F_HEAD = "Georgia,'Times New Roman',serif"
F_BODY = "-apple-system,'Segoe UI',Arial,sans-serif"


def fmt_date_de(iso):
    d = dt.date.fromisoformat(iso)
    monate = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    return f"{d.day}. {monate[d.month - 1]} {d.year}"


def richtung(chg, schwellen=(3, 0.8, 0.15)):
    hi, mid, lo = schwellen
    if chg is None:
        return "unveraendert"
    if chg >= hi:
        return "kraeftig gestiegen"
    if chg >= mid:
        return "spuerbar gestiegen"
    if chg > lo:
        return "leicht gestiegen"
    if chg > -lo:
        return "praktisch unveraendert"
    if chg > -mid:
        return "leicht gefallen"
    if chg > -hi:
        return "spuerbar gefallen"
    return "deutlich gefallen"


# --------------------------------------------------------------- Chart-PNG
def render_chart_png(series, days=None, color=SPARK, w=1120, h=380):
    """series: [[date, level], ...]. PNG-Bytes fuer Inline-Einbettung."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    pts = series[-days:] if days else series
    if len(pts) < 2:
        pts = series
    xs = [dt.date.fromisoformat(p[0]) for p in pts]
    ys = [p[1] for p in pts]

    fig, ax = plt.subplots(figsize=(w / 100, h / 100), dpi=100)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.plot(xs, ys, color=color, linewidth=2.4, solid_capstyle="round", zorder=4)
    ax.fill_between(xs, ys, min(ys), color=color, alpha=0.08, zorder=2)
    ax.scatter([xs[-1]], [ys[-1]], color=color, s=34, zorder=5)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#cfcac2")
    ax.tick_params(axis="x", colors="#8a8578", labelsize=11, length=0, pad=8)
    ax.tick_params(axis="y", colors="#8a8578", labelsize=11, length=0, pad=6)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    ax.grid(axis="y", color="#efece5", linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.margins(x=0.01)
    fig.tight_layout(pad=0.8)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------- HTML-Bausteine
def eyebrow(text):
    return (f'<div style="font:700 11px/1.4 {F_BODY};letter-spacing:.09em;'
            f'text-transform:uppercase;color:{SPARK};margin:0 0 8px">{html.escape(text)}</div>')


def headline_html(text):
    return f'<h1 style="font:700 27px/1.28 {F_HEAD};color:{INK};margin:0 0 8px">{html.escape(text)}</h1>'


def meta_line(text):
    return f'<div style="font:13px/1.5 {F_BODY};color:{SUB};margin:0 0 20px">{html.escape(text)}</div>'


def hr():
    return f'<hr style="border:none;border-top:1px solid {RULE};margin:22px 0">'


def para(inner_html, bold=False, size=15):
    weight = "700" if bold else "400"
    return f'<p style="font:{weight} {size}px/1.62 {F_BODY};color:{INK};margin:0 0 12px">{inner_html}</p>'


def pct_span(chg):
    if chg is None:
        return f'<span style="color:{SUB}">—</span>'
    color = UP if chg >= 0 else DOWN
    return f'<span style="color:{color};font-weight:700">{chg:+.2f} %</span>'


def chart_block(cid_or_src, caption, source_note):
    return (f'<div style="margin:6px 0 20px">'
            f'<div style="font:600 13.5px/1.4 {F_BODY};color:{INK};margin:0 0 10px">{html.escape(caption)}</div>'
            f'<img src="{cid_or_src}" width="1120" style="width:100%;max-width:600px;height:auto;display:block" '
            f'alt="{html.escape(caption)}">'
            f'<div style="font:italic 11.5px/1.5 {F_BODY};color:{SUB};margin:9px 0 0">{html.escape(source_note)}</div>'
            f'</div>')


def scoreboard(rows):
    """rows: [(name, level_txt, chg_val_or_None, extra_txt_or_None), ...]"""
    trs = ""
    for name, level_txt, chg, extra in rows:
        trs += (f'<tr>'
                f'<td style="padding:10px 0;border-bottom:1px solid {RULE};font:600 14.5px {F_BODY};color:{INK}">{html.escape(name)}</td>'
                f'<td style="padding:10px 10px;border-bottom:1px solid {RULE};font:14.5px {F_BODY};color:{INK};text-align:right;white-space:nowrap">{level_txt}</td>'
                f'<td style="padding:10px 0;border-bottom:1px solid {RULE};text-align:right;white-space:nowrap">{pct_span(chg)}</td>'
                f'</tr>')
    return f'<table style="width:100%;border-collapse:collapse;margin:4px 0 22px">{trs}</table>'


def mover_table(title, rows, key):
    if not rows:
        return ""
    trs = ""
    for r in rows:
        chg = r[key]
        trs += (f'<tr>'
                f'<td style="padding:8px 0;border-bottom:1px solid {RULE};font:14px {F_BODY};color:{INK}">'
                f'{html.escape(r["n"])}<br><span style="color:{SUB};font-size:12px">{html.escape(r["s"] or "")}</span></td>'
                f'<td style="padding:8px 8px;border-bottom:1px solid {RULE};font:14px {F_BODY};color:{INK};text-align:right;white-space:nowrap">{r["p"]:,.2f} $</td>'
                f'<td style="padding:8px 0;border-bottom:1px solid {RULE};text-align:right;white-space:nowrap">{pct_span(chg)}</td>'
                f'</tr>')
    return (f'<div style="margin:0 0 22px">'
            f'<div style="font:700 11.5px/1.4 {F_BODY};letter-spacing:.05em;text-transform:uppercase;'
            f'color:{SUB};margin:0 0 8px">{html.escape(title)}</div>'
            f'<table style="width:100%;border-collapse:collapse">{trs}</table></div>')


def markets_table(markets, key="d1", label="Tag"):
    rows = ""
    for k, name in MARKET_NAMES.items():
        c = markets.get(k)
        if not c:
            continue
        v = c.get(key)
        rows += (f'<tr>'
                 f'<td style="padding:8px 0;border-bottom:1px solid {RULE};font:14px {F_BODY};color:{INK}">{html.escape(name)}</td>'
                 f'<td style="padding:8px 8px;border-bottom:1px solid {RULE};font:14px {F_BODY};color:{INK};text-align:right;white-space:nowrap">{c["level"]:,.2f}</td>'
                 f'<td style="padding:8px 0;border-bottom:1px solid {RULE};text-align:right;white-space:nowrap">{pct_span(v)}</td>'
                 f'</tr>')
    if not rows:
        return ""
    return (f'<div style="margin:0 0 22px">'
            f'<div style="font:700 11.5px/1.4 {F_BODY};letter-spacing:.05em;text-transform:uppercase;'
            f'color:{SUB};margin:0 0 8px">Traditionelle Maerkte ({label})</div>'
            f'<table style="width:100%;border-collapse:collapse">{rows}</table></div>')


def footer_html(asof, note=""):
    return (hr() +
            f'<p style="font:12px/1.65 {F_BODY};color:{SUB};margin:0">'
            f'Automatisch erzeugt · Stand {asof} · Preise: TCGplayer Market Price (tcgcsv.com), '
            f'Skinport, Yahoo Finance. {note}</p>')


def wrap(inner_html):
    return (f'<div style="background:{PAPER};padding:8px 0">'
            f'<div style="font-family:{F_BODY};max-width:600px;margin:0 auto;padding:32px 24px;'
            f'background:#ffffff;color:{INK};border:1px solid {RULE}">{inner_html}</div></div>')


# ---------------------------------------------------------------- Kennzahlen
def day_stats(block):
    o = block["overview"]
    chg = round((o["level"] / o["prev"] - 1) * 100, 2) if o.get("prev") else None
    return {"level": o["level"], "chg": chg, "asof": block["asof"], "adv": o.get("adv"), "dec": o.get("dec"),
            "ath": o.get("ath")}


def week_stats(block):
    tail = block["series_tail"]
    last_d = dt.date.fromisoformat(tail[-1][0])
    week = [p for p in tail if (last_d - dt.date.fromisoformat(p[0])).days <= 7]
    anchor = None
    for p in tail:
        if (last_d - dt.date.fromisoformat(p[0])).days >= 7:
            anchor = p
    level = tail[-1][1]
    chg = round((level / anchor[1] - 1) * 100, 2) if anchor else None
    return {"level": level, "chg": chg, "hi": max(p[1] for p in week), "lo": min(p[1] for p in week),
            "asof": tail[-1][0]}


def lead_story(stat_map):
    """Waehlt den Index mit der groessten |Veraenderung| als Aufmacher-Story."""
    named = {IDX_LABELS.get(k, k): v for k, v in stat_map.items() if v and v.get("chg") is not None}
    if not named:
        return None, None
    name, stat = max(named.items(), key=lambda kv: abs(kv[1]["chg"]))
    return name, stat


# ------------------------------------------------------------------- Daily
def build_daily(summary, heute):
    cards, sealed = summary.get(CARD_INDEX), summary.get(SEALED_INDEX)
    cs2 = summary.get(CS2_INDEX)
    markets = summary.get("MARKETS") or {}

    c_stat, s_stat = day_stats(cards), day_stats(sealed)
    cs_stat = day_stats(cs2) if cs2 else None
    stat_map = {"SPK500": c_stat, "SPKS": s_stat, "CS2500": cs_stat}

    lead_name, lead = lead_story(stat_map)
    if lead is None:
        eyebrow_txt, hl = "Tagesueberblick", "Ruhiger Handelstag ohne nennenswerte Ausschlaege"
    else:
        chg = lead["chg"]
        short = lead_name.split(" (")[0]
        if chg is not None and lead.get("ath") and lead["level"] >= lead["ath"] * 0.999:
            hl = f"{short} auf Allzeithoch"
        elif abs(chg) < 0.15:
            hl = f"{short}: kaum Bewegung am Markt"
        elif chg >= 3:
            hl = f"{short} springt um {chg:.1f} %"
        elif chg > 0:
            hl = f"{short} steigt um {chg:.1f} %"
        elif chg > -3:
            hl = f"{short} faellt um {abs(chg):.1f} %"
        else:
            hl = f"{short} bricht um {abs(chg):.1f} % ein"
        eyebrow_txt = "Tagesueberblick"

    saetze = [f"Der Kartenindex (SPK500) schliesst bei <b>{c_stat['level']:,.2f}</b> Punkten "
              f"({pct_span(c_stat['chg'])}), der Sealed-Index (SPKS) bei <b>{s_stat['level']:,.2f}</b> "
              f"({pct_span(s_stat['chg'])})"]
    if cs_stat:
        saetze[0] += f" und der CS2-Skin-Index (CS2500) bei <b>{cs_stat['level']:,.2f}</b> ({pct_span(cs_stat['chg'])})"
    saetze[0] += "."
    body_p1 = "".join(saetze)

    adv, dec = c_stat.get("adv") or 0, c_stat.get("dec") or 0
    if adv + dec > 0:
        if adv > dec * 1.5:
            breadth = f"{adv} Gewinnern standen nur {dec} Verlierer gegenueber – die Marktbreite war klar positiv."
        elif dec > adv * 1.5:
            breadth = f"{dec} Verlierern standen nur {adv} Gewinner gegenueber – die Marktbreite war negativ."
        else:
            breadth = f"{adv} Gewinner und {dec} Verlierer hielten sich die Waage."
    else:
        breadth = "Keine ausreichende Marktbreite fuer eine Aussage."
    bottom_line = f"<b>{breadth}</b>"

    sp = markets.get("SP500")
    vgl = ""
    if sp and sp.get("d1") is not None:
        gold = markets.get("GOLD", {}).get("d1")
        btc = markets.get("BITCOIN", {}).get("d1")
        vgl = (f'Zum Vergleich: S&amp;P&nbsp;500 {pct_span(sp["d1"])}, Gold {pct_span(gold)}, '
               f'Bitcoin {pct_span(btc)} (jeweils zum Vortag).')

    score_rows = [
        (IDX_LABELS["SPK500"], f"{c_stat['level']:,.2f}", c_stat["chg"], None),
        (IDX_LABELS["SPKS"], f"{s_stat['level']:,.2f}", s_stat["chg"], None),
    ]
    if cs_stat:
        score_rows.append((IDX_LABELS["CS2500"], f"{cs_stat['level']:,.2f}", cs_stat["chg"], None))

    def render(chart_src):
        parts = [
            eyebrow(eyebrow_txt),
            headline_html(hl),
            meta_line(fmt_date_de(cards["asof"])),
            scoreboard(score_rows),
            para(body_p1),
            para(bottom_line),
            chart_block(chart_src, "SPK500 – letzte 30 Tage", "Quelle: TCGplayer Market Price via tcgcsv.com"),
        ]
        if vgl:
            parts.append(para(vgl, size=13.5))
        parts.append(footer_html(cards["asof"]))
        return wrap("".join(parts))

    chart_series = load_full_series("SPK500")
    subject = f"{hl} · SPK500 {c_stat['level']:,.0f}"
    text_fallback = (f"{hl}\n\nSPK500 {c_stat['level']:,.2f} ({c_stat['chg']}%)\n"
                      f"SPKS {s_stat['level']:,.2f} ({s_stat['chg']}%)\n"
                      + (f"CS2500 {cs_stat['level']:,.2f} ({cs_stat['chg']}%)\n" if cs_stat else ""))
    return {
        "subject": subject, "render": render, "chart_series": chart_series, "chart_days": 30,
        "asof": cards["asof"], "text_fallback": text_fallback,
    }


# ------------------------------------------------------------------ Weekly
def build_weekly(summary, heute):
    cards, sealed = summary.get(CARD_INDEX), summary.get(SEALED_INDEX)
    cs2 = summary.get(CS2_INDEX)
    markets = summary.get("MARKETS") or {}

    c_stat, s_stat = week_stats(cards), week_stats(sealed)
    cs_stat = week_stats(cs2) if cs2 and len(cs2.get("series_tail", [])) > 1 else None
    stat_map = {"SPK500": c_stat, "SPKS": s_stat, "CS2500": cs_stat}

    lead_name, lead = lead_story(stat_map)
    if lead is None:
        hl = "Ruhige Woche an den Sammlermaerkten"
    else:
        chg = lead["chg"]
        short = lead_name.split(" (")[0]
        if abs(chg) < 0.3:
            hl = f"{short}: seitwaertige Woche"
        elif chg >= 5:
            hl = f"{short} legt kraeftig zu – {chg:+.1f} % in dieser Woche"
        elif chg > 0:
            hl = f"{short} gewinnt {chg:.1f} % hinzu"
        elif chg > -5:
            hl = f"{short} verliert {abs(chg):.1f} % in dieser Woche"
        else:
            hl = f"{short} korrigiert deutlich um {abs(chg):.1f} %"

    def chg_paren(chg):
        return f" ({chg:+.2f} %)" if chg is not None else ""

    saetze = [f"Der Kartenindex ist diese Woche {richtung(c_stat['chg'])}"
              f"{chg_paren(c_stat['chg'])} "
              f"und schliesst bei <b>{c_stat['level']:,.2f}</b> Punkten "
              f"(Wochenspanne {c_stat['lo']:,.0f}\u2013{c_stat['hi']:,.0f})."]
    o = cards["overview"]
    if o.get("ath") and c_stat["level"] >= o["ath"] * 0.995:
        saetze.append("Damit notiert er nahe seinem Allzeithoch.")
    saetze.append(f"Der Sealed-Index ist {richtung(s_stat['chg'])}"
                  f"{chg_paren(s_stat['chg'])} "
                  f"und steht bei <b>{s_stat['level']:,.2f}</b> Punkten.")
    if cs_stat:
        saetze.append(f"Der CS2-Skin-Index ist {richtung(cs_stat['chg'])}"
                      f"{chg_paren(cs_stat['chg'])} "
                      f"und liegt bei <b>{cs_stat['level']:,.2f}</b> Punkten.")
    intro = " ".join(saetze)

    c, s = c_stat["chg"], s_stat["chg"]
    if c is not None and s is not None:
        if abs(c - s) < 0.3:
            vergleich = "Karten und Sealed-Produkte bewegten sich weitgehend im Gleichschritt."
        elif c > s:
            vergleich = "Einzelkarten liefen diese Woche besser als Sealed-Produkte."
        else:
            vergleich = "Sealed-Produkte liefen diese Woche besser als Einzelkarten."
    else:
        vergleich = ""
    bottom_line = f"<b>{vergleich}</b>" if vergleich else ""

    sp = markets.get("SP500")
    vgl = ""
    if sp and sp.get("w1") is not None:
        gold = markets.get("GOLD", {}).get("w1")
        btc = markets.get("BITCOIN", {}).get("w1")
        vgl = (f'Zum Vergleich bewegte sich der S&amp;P&nbsp;500 in derselben Zeit um {pct_span(sp["w1"])}, '
               f'Gold um {pct_span(gold)} und Bitcoin um {pct_span(btc)}.')

    score_rows = [
        (IDX_LABELS["SPK500"], f"{c_stat['level']:,.2f}", c_stat["chg"], None),
        (IDX_LABELS["SPKS"], f"{s_stat['level']:,.2f}", s_stat["chg"], None),
    ]
    if cs_stat:
        score_rows.append((IDX_LABELS["CS2500"], f"{cs_stat['level']:,.2f}", cs_stat["chg"], None))

    def render(chart_src):
        parts = [
            eyebrow("Wochenbriefing"),
            headline_html(hl),
            meta_line(f"Woche bis {fmt_date_de(cards['asof'])}"),
            scoreboard(score_rows),
            para(intro),
        ]
        if bottom_line:
            parts.append(para(bottom_line))
        if vgl:
            parts.append(para(vgl, size=13.5))
        parts.append(chart_block(chart_src, "SPK500 – letzte 180 Tage",
                                  "Quelle: TCGplayer Market Price via tcgcsv.com"))
        parts.append(hr())
        parts.append(mover_table("Karten – Top-Wochengewinner", cards.get("weekly_up"), "wchg"))
        parts.append(mover_table("Karten – Top-Wochenverlierer", cards.get("weekly_dn"), "wchg"))
        parts.append(mover_table("Sealed – Top-Wochengewinner", sealed.get("weekly_up"), "wchg"))
        parts.append(mover_table("Sealed – Top-Wochenverlierer", sealed.get("weekly_dn"), "wchg"))
        if cs2:
            parts.append(mover_table("CS2 – Top-Wochengewinner", cs2.get("weekly_up"), "wchg"))
            parts.append(mover_table("CS2 – Top-Wochenverlierer", cs2.get("weekly_dn"), "wchg"))
        parts.append(markets_table(markets, key="w1", label="Woche"))
        parts.append(footer_html(cards["asof"], "Wochenaenderungen nur zwischen bestaetigten Preisen."))
        return wrap("".join(parts))

    chart_series = load_full_series("SPK500")
    subject = f"{hl} · SPK500 {c_stat['level']:,.0f}"
    text_fallback = f"{hl}\n\nSPK500 {c_stat['level']:,.2f}\nSPKS {s_stat['level']:,.2f}\n"
    return {
        "subject": subject, "render": render, "chart_series": chart_series, "chart_days": 180,
        "asof": cards["asof"], "text_fallback": text_fallback,
    }


# --------------------------------------------------------------------- I/O
def load_newsletter_listing():
    lst_path = os.path.join(SITE_DATA, "newsletters.js")
    if not os.path.isfile(lst_path):
        return []
    with open(lst_path, encoding="utf-8") as f:
        txt = f.read()
    try:
        raw = json.loads(txt[txt.index("=") + 1:].rstrip("; \n"))
    except (ValueError, json.JSONDecodeError):
        return []
    # Altformat (Liste von Datumsstrings) -> neues Format migrieren
    out = []
    for item in raw:
        if isinstance(item, str):
            out.append({"d": item, "t": "weekly"})
        else:
            out.append(item)
    return out


def save_newsletter_listing(listing):
    lst_path = os.path.join(SITE_DATA, "newsletters.js")
    with open(lst_path, "w", encoding="utf-8") as f:
        f.write("window.NEWSLETTERS=" + json.dumps(listing, ensure_ascii=False) + ";")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "weekly"], default="daily")
    ap.add_argument("--dry-run", action="store_true",
                    help="nur Archivdatei erzeugen, keine E-Mail versenden")
    args = ap.parse_args()

    with open(os.path.join(SITE_DATA, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    if not summary.get(CARD_INDEX) or not summary.get(SEALED_INDEX):
        print("summary.json unvollstaendig – zuerst build_indices.py ausfuehren.")
        return 1

    heute = dt.date.today().isoformat()
    builder = build_daily if args.mode == "daily" else build_weekly
    out = builder(summary, heute)

    chart_png = render_chart_png(out["chart_series"], days=out["chart_days"])
    data_uri = "data:image/png;base64," + base64.b64encode(chart_png).decode("ascii")
    archive_html = out["render"](data_uri)

    os.makedirs(NL_DIR, exist_ok=True)
    arch = os.path.join(NL_DIR, f"{heute}-{args.mode}.html")
    with open(arch, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset='utf-8'><title>{html.escape(out['subject'])}</title>"
                f"{archive_html}")

    listing = load_newsletter_listing()
    if not any(item["d"] == heute and item["t"] == args.mode for item in listing):
        listing.insert(0, {"d": heute, "t": args.mode})
    save_newsletter_listing(listing)
    print(f"Archiv geschrieben: {arch}")

    if args.dry_run:
        print("Dry-Run – keine E-Mail versendet.")
        return 0

    absender = os.environ.get("GMAIL_ADDRESS")
    passwort = os.environ.get("GMAIL_APP_PASSWORD")
    raw_to = os.environ.get("NEWSLETTER_TO", "")
    empfaenger = [e.strip() for e in raw_to.split(",") if e.strip()]
    if not empfaenger and absender:
        empfaenger = [absender]
    if not absender or not passwort:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD nicht gesetzt.")
        return 1
    if not empfaenger:
        print("Kein gueltiger Empfaenger (NEWSLETTER_TO leer und kein Absender).")
        return 1

    cid = "chart1"
    email_html = out["render"](f"cid:{cid}")

    msg = MIMEMultipart("related")
    msg["Subject"] = out["subject"]
    msg["From"] = absender
    msg["To"] = absender
    msg["Bcc"] = ", ".join(empfaenger)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(out["text_fallback"], "plain", "utf-8"))
    alt.attach(MIMEText(email_html, "html", "utf-8"))
    msg.attach(alt)
    img = MIMEImage(chart_png, _subtype="png")
    img.add_header("Content-ID", f"<{cid}>")
    img.add_header("Content-Disposition", "inline", filename="chart.png")
    msg.attach(img)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
        srv.login(absender, passwort)
        srv.sendmail(absender, [absender] + empfaenger, msg.as_string())
    print(f"Newsletter ({args.mode}) an {len(empfaenger)} Empfaenger versendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
