# -*- coding: utf-8 -*-
"""
Wöchentlicher Newsletter (Sonntag): Zusammenfassung beider Indizes mit
automatischem Marktkommentar und den größten Wochen-Movers.

Versand per Gmail-SMTP. Benötigte Umgebungsvariablen (GitHub-Secrets):
  GMAIL_ADDRESS       Absender-Gmail-Adresse
  GMAIL_APP_PASSWORD  Gmail-App-Passwort (nicht das normale Passwort!)
  NEWSLETTER_TO       Empfänger (optional, Standard = GMAIL_ADDRESS)

Zusätzlich wird jede Ausgabe unter site/newsletter/JJJJ-MM-TT.html archiviert
und in site/data/newsletters.js gelistet (Archiv auf der Website).

Aufruf:  python scripts/send_newsletter.py [--dry-run]
"""
import argparse
import datetime as dt
import html
import json
import os
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from common import CARD_INDEX, ROOT, SEALED_INDEX, SITE_DATA

NL_DIR = os.path.join(ROOT, "site", "newsletter")
CS2_INDEX = "CS2500"
MARKET_NAMES = {"SP500": "S&P 500", "DAX": "DAX", "NASDAQ100": "NASDAQ 100",
                "EUROSTOXX50": "EuroStoxx 50", "MSCIWORLD": "MSCI World",
                "GOLD": "Gold", "SILVER": "Silber", "BITCOIN": "Bitcoin"}


def week_stats(block):
    """Level, Wochenänderung, Wochen-Hoch/Tief aus series_tail."""
    tail = block["series_tail"]
    last_d = dt.date.fromisoformat(tail[-1][0])
    week = [p for p in tail if (last_d - dt.date.fromisoformat(p[0])).days <= 7]
    anchor = None
    for p in tail:
        if (last_d - dt.date.fromisoformat(p[0])).days >= 7:
            anchor = p
    level = tail[-1][1]
    chg = round((level / anchor[1] - 1) * 100, 2) if anchor else None
    return {"level": level, "chg": chg,
            "hi": max(p[1] for p in week), "lo": min(p[1] for p in week),
            "asof": tail[-1][0]}


def kommentar(cards, sealed, c_stat, s_stat):
    """Regelbasierter deutscher Marktkommentar aus den Zahlen."""
    saetze = []

    def richtung(chg):
        if chg is None:
            return "seitwärts"
        if chg >= 3:
            return "kräftig gestiegen"
        if chg >= 0.8:
            return "spürbar gestiegen"
        if chg > 0.1:
            return "leicht gestiegen"
        if chg > -0.1:
            return "praktisch unverändert"
        if chg > -0.8:
            return "leicht gefallen"
        if chg > -3:
            return "spürbar gefallen"
        return "deutlich gefallen"

    c, s = c_stat["chg"], s_stat["chg"]
    saetze.append(
        f"Der Karten-Index ist in dieser Woche {richtung(c)}"
        f"{f' ({c:+.2f} %)' if c is not None else ''} und schließt bei "
        f"{c_stat['level']:,.2f} Punkten.")
    o = cards["overview"]
    if o.get("ath") and c_stat["level"] >= o["ath"] * 0.995:
        saetze.append("Damit notiert er in unmittelbarer Nähe seines Allzeithochs.")
    saetze.append(
        f"Der Sealed-Index ist {richtung(s)}"
        f"{f' ({s:+.2f} %)' if s is not None else ''} und steht bei "
        f"{s_stat['level']:,.2f} Punkten.")
    if c is not None and s is not None:
        if abs(c - s) < 0.3:
            saetze.append("Karten und Sealed-Produkte bewegten sich damit weitgehend im Gleichschritt.")
        elif c > s:
            saetze.append("Einzelkarten liefen diese Woche besser als Sealed-Produkte.")
        else:
            saetze.append("Sealed-Produkte liefen diese Woche besser als Einzelkarten.")
    adv, dec = o.get("adv"), o.get("dec")
    if adv is not None and (adv + dec) > 0:
        if adv > dec * 1.5:
            saetze.append(f"Die Marktbreite war klar positiv ({adv} Gewinner gegenüber {dec} Verlierern am letzten Handelstag).")
        elif dec > adv * 1.5:
            saetze.append(f"Die Marktbreite war negativ ({adv} Gewinner gegenüber {dec} Verlierern am letzten Handelstag).")
        else:
            saetze.append(f"Die Marktbreite war ausgeglichen ({adv} Gewinner, {dec} Verlierer am letzten Handelstag).")
    up = cards.get("weekly_up") or []
    if up:
        t = up[0]
        saetze.append(
            f"Auffälligster Wochengewinner bei den Karten: {t['n']} ({t['s']}) "
            f"mit {t['wchg']:+.1f} % auf {t['p']:,.2f} $. ")
    dn = cards.get("weekly_dn") or []
    if dn and dn[0]["wchg"] < 0:
        t = dn[0]
        saetze.append(
            f"Größter Wochenverlierer: {t['n']} ({t['s']}) mit {t['wchg']:+.1f} %.")
    return " ".join(saetze)


def mover_tabelle(titel_txt, rows, key):
    if not rows:
        return ""
    tr = ""
    for r in rows:
        chg = r[key]
        farbe = "#1a9850" if chg >= 0 else "#d73027"
        tr += (f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee'>"
               f"{html.escape(r['n'])}<br><span style='color:#888;font-size:12px'>"
               f"{html.escape(r['s'] or '')}</span></td>"
               f"<td style='padding:6px 10px;text-align:right;border-bottom:1px solid #eee'>"
               f"{r['p']:,.2f} $</td>"
               f"<td style='padding:6px 10px;text-align:right;color:{farbe};"
               f"border-bottom:1px solid #eee'>{chg:+.2f} %</td></tr>")
    return (f"<h3 style='margin:18px 0 6px'>{titel_txt}</h3>"
            f"<table style='border-collapse:collapse;width:100%;font-size:14px'>{tr}</table>")


def index_block(name, stat):
    chg = stat["chg"]
    farbe = "#1a9850" if (chg or 0) >= 0 else "#d73027"
    return (f"<td style='padding:12px 18px;background:#f7f7f9;border-radius:10px'>"
            f"<div style='font-size:12px;color:#666'>{name}</div>"
            f"<div style='font-size:24px;font-weight:700'>{stat['level']:,.2f}</div>"
            f"<div style='color:{farbe};font-weight:600'>"
            f"{f'{chg:+.2f} % (Woche)' if chg is not None else '—'}</div>"
            f"<div style='font-size:12px;color:#666'>Woche: {stat['lo']:,.2f} – {stat['hi']:,.2f}</div></td>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="nur Archivdatei erzeugen, keine E-Mail senden")
    args = ap.parse_args()

    with open(os.path.join(SITE_DATA, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    cards, sealed = summary.get(CARD_INDEX), summary.get(SEALED_INDEX)
    cs2 = summary.get(CS2_INDEX)
    markets = summary.get("MARKETS") or {}
    if not cards or not sealed:
        print("summary.json unvollständig – zuerst build_indices.py ausführen.")
        return 1

    c_stat, s_stat = week_stats(cards), week_stats(sealed)
    cs_stat = week_stats(cs2) if cs2 and len(cs2.get("series_tail", [])) > 1 else None
    heute = dt.date.today().isoformat()
    komm = kommentar(cards, sealed, c_stat, s_stat)
    if cs_stat is not None:
        r = cs_stat["chg"]
        komm += (f" Der CS2-Skin-Index steht bei {cs_stat['level']:,.2f} Punkten"
                 f"{f' ({r:+.2f} % zur Vorwoche)' if r is not None else ''}.")
    sp = markets.get("SP500")
    if sp and sp.get("w1") is not None:
        komm += (f" Zum Vergleich: Der S&P 500 bewegte sich in derselben Zeit um "
                 f"{sp['w1']:+.2f} %, Gold um "
                 f"{markets.get('GOLD', {}).get('w1', 0) or 0:+.2f} % und Bitcoin um "
                 f"{markets.get('BITCOIN', {}).get('w1', 0) or 0:+.2f} %.")

    markt_zeilen = ""
    for key, name in MARKET_NAMES.items():
        c = markets.get(key)
        if not c:
            continue
        w1 = c.get("w1")
        farbe = "#1a9850" if (w1 or 0) >= 0 else "#d73027"
        markt_zeilen += (f"<tr><td style='padding:5px 10px;border-bottom:1px solid #eee'>{name}</td>"
                         f"<td style='padding:5px 10px;text-align:right;border-bottom:1px solid #eee'>"
                         f"{c['level']:,.2f}</td>"
                         f"<td style='padding:5px 10px;text-align:right;color:{farbe};"
                         f"border-bottom:1px solid #eee'>{f'{w1:+.2f} %' if w1 is not None else '—'}</td></tr>")
    markt_block = (f"<h3 style='margin:18px 0 6px'>Traditionelle Märkte (Woche)</h3>"
                   f"<table style='border-collapse:collapse;width:100%;font-size:14px'>"
                   f"<tr><th style='text-align:left;padding:5px 10px;color:#888'>Markt</th>"
                   f"<th style='text-align:right;padding:5px 10px;color:#888'>Stand</th>"
                   f"<th style='text-align:right;padding:5px 10px;color:#888'>Woche</th></tr>"
                   f"{markt_zeilen}</table>") if markt_zeilen else ""

    body = f"""
<div style="font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:auto;color:#1c1c1e">
  <h1 style="font-size:20px">Pokémon-Markt – Wochenbericht {heute}</h1>
  <table style="width:100%;border-spacing:8px 0"><tr>
    {index_block('Karten-Index (SPK500)', c_stat)}
    {index_block('Sealed-Index (SPKS)', s_stat)}
    {index_block('CS2-Index (CS2500)', cs_stat) if cs_stat else ''}
  </tr></table>
  <p style="line-height:1.55">{komm}</p>
  {mover_tabelle('Karten – Top-Wochengewinner', cards.get('weekly_up'), 'wchg')}
  {mover_tabelle('Karten – Top-Wochenverlierer', cards.get('weekly_dn'), 'wchg')}
  {mover_tabelle('Sealed – Top-Wochengewinner', sealed.get('weekly_up'), 'wchg')}
  {mover_tabelle('Sealed – Top-Wochenverlierer', sealed.get('weekly_dn'), 'wchg')}
  {mover_tabelle('CS2 – Top-Wochengewinner', (cs2 or {}).get('weekly_up'), 'wchg') if cs2 else ''}
  {mover_tabelle('CS2 – Top-Wochenverlierer', (cs2 or {}).get('weekly_dn'), 'wchg') if cs2 else ''}
  {markt_block}
  <p style="color:#888;font-size:12px;margin-top:24px">
    Datenstand: {cards['asof']} · Preise: TCGplayer Market Price (via tcgcsv.com).
    Wochenänderungen nur zwischen bestätigten Preisen.
    Automatisch erzeugter Bericht des privaten Pokémon-Index-Dashboards.</p>
</div>"""

    os.makedirs(NL_DIR, exist_ok=True)
    arch = os.path.join(NL_DIR, f"{heute}.html")
    with open(arch, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><meta charset='utf-8'>"
                f"<title>Wochenbericht {heute}</title>{body}")
    listing = []
    lst_path = os.path.join(SITE_DATA, "newsletters.js")
    if os.path.isfile(lst_path):
        with open(lst_path, encoding="utf-8") as f:
            txt = f.read()
            listing = json.loads(txt[txt.index("=") + 1:].rstrip("; \n"))
    if heute not in listing:
        listing.insert(0, heute)
    with open(lst_path, "w", encoding="utf-8") as f:
        f.write("window.NEWSLETTERS=" + json.dumps(listing) + ";")
    print(f"Archiv geschrieben: {arch}")

    if args.dry_run:
        print("Dry-Run – keine E-Mail versendet.")
        return 0

    absender = os.environ.get("GMAIL_ADDRESS")
    passwort = os.environ.get("GMAIL_APP_PASSWORD")
    empfaenger = os.environ.get("NEWSLETTER_TO", absender)
    if not absender or not passwort:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD nicht gesetzt.")
        return 1
    msg = MIMEMultipart("alternative")
    chg_txt = f"{c_stat['chg']:+.2f} %" if c_stat["chg"] is not None else "—"
    msg["Subject"] = f"Pokémon-Index Wochenbericht {heute}: SPK500 {c_stat['level']:,.0f} ({chg_txt})"
    msg["From"] = absender
    msg["To"] = empfaenger
    msg.attach(MIMEText(body, "html", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
        srv.login(absender, passwort)
        srv.sendmail(absender, [empfaenger], msg.as_string())
    print(f"Newsletter an {empfaenger} versendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
