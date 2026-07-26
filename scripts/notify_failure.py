# -*- coding: utf-8 -*-
"""Fehlerbenachrichtigung per E-Mail für GitHub Actions.

Vorher fiel ein roter Workflow nur auf, wenn man von sich aus in den
Actions-Tab schaute – bei einer Pipeline, die täglich Daten fortschreibt, sind
das schnell mehrere verlorene Tage. Der Aufruf steht in jedem Workflow unter
`if: failure()`.

Nutzt dieselben Secrets wie der Newsletter. Fehlen sie, endet das Skript
still mit Exitcode 0 (die Benachrichtigung darf den Lauf nicht weiter
verschlechtern).

Aufruf:  python scripts/notify_failure.py "Kurzbeschreibung"
"""
from __future__ import annotations

import datetime as dt
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


def main() -> int:
    betreff_kurz = sys.argv[1] if len(sys.argv) > 1 else "Pipeline-Fehler"
    absender = os.environ.get("GMAIL_ADDRESS")
    passwort = os.environ.get("GMAIL_APP_PASSWORD")
    empfaenger = [e.strip() for e in os.environ.get("NEWSLETTER_TO", "").split(",")
                  if e.strip()] or ([absender] if absender else [])
    if not absender or not passwort or not empfaenger:
        print("Keine Mail-Zugangsdaten – Benachrichtigung übersprungen.")
        return 0

    run_url = os.environ.get("RUN_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    workflow = os.environ.get("GITHUB_WORKFLOW", "")
    job = os.environ.get("GITHUB_JOB", "")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    body = (f"{betreff_kurz}\n\n"
            f"Zeit:      {stamp}\n"
            f"Repository:{repo}\n"
            f"Workflow:  {workflow}\n"
            f"Job:       {job}\n"
            f"Protokoll: {run_url}\n\n"
            f"Die Daten wurden NICHT veröffentlicht, solange der Lauf rot ist.\n"
            f"Häufige Ursachen:\n"
            f"  - Quelle nicht erreichbar (tcgcsv, Skinport, Yahoo/Stooq)\n"
            f"  - Validierung hat einen Datenbruch erkannt (Zeilenzahl, Lücke)\n"
            f"  - Push-Konflikt mit einem lokalen Commit\n")

    msg = EmailMessage()
    msg["Subject"] = f"[PokeIndex] {betreff_kurz}"
    msg["From"] = absender
    msg["To"] = ", ".join(empfaenger)
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
        srv.login(absender, passwort)
        srv.send_message(msg)
    print(f"Fehlerbenachrichtigung an {len(empfaenger)} Empfänger gesendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
