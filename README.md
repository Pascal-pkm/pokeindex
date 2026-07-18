# PokéIndex – privates Multi-Asset-Dashboard

Eigenes Dashboard nach dem Vorbild von „S&Poké 500", erweitert auf alle
Anlageklassen der Masterarbeit:

- **SPK500** – Top 500 Pokémon-Einzelkarten (TCGplayer Market Price, täglich)
- **SPKS** – Sealed-Index, gleiche Regeln (täglich)
- **CS2500** – Top 500 CS2-Skins (Skinport-API, täglich) plus gleichgewichteter
  Index nach Masterarbeits-Methodik (Steam-Historie seit 2013, täglich fortgeführt)
- **Märkte** – S&P 500, DAX, NASDAQ 100, EuroStoxx 50, MSCI World, Gold, Silber,
  Bitcoin (Historie 2013–2026, täglich via Yahoo Finance fortgeschrieben)
- **Bestände** – PriceCharting-Scrapes (≈25.000 Karten, ≈1.800 Sealed) und
  Steam-Market-Scrapes (≈13.700 CS2-Items) mit monatlicher Historie

Preise werden täglich automatisch abgezogen, alle Indizes neu berechnet, die
Website veröffentlicht und sonntags ein Newsletter über alle Klassen verschickt.

## Ordnerstruktur

```
Pokemon Index und Website/
├── README.md                  diese Anleitung
├── requirements.txt           Python-Abhängigkeiten (requests, py7zr)
├── .github/workflows/
│   ├── daily.yml              täglich 20:30 UTC: Preise ziehen, Indizes, Deploy
│   ├── backfill.yml           lädt die Historie ab 08.02.2024 nach (bis fertig)
│   └── newsletter.yml         sonntags 07:00 UTC: Newsletter per Gmail
├── scripts/
│   ├── common.py              gemeinsame Helfer + Index-Regeln (Parameter)
│   ├── fetch_prices.py        täglicher Abzug von tcgcsv.com (TCGplayer)
│   ├── fetch_cs2.py           täglicher CS2-Abzug (Skinport-API, ohne Login)
│   ├── fetch_markets.py       tägliche Marktdaten (Yahoo Finance)
│   ├── backfill_archive.py    Historie aus dem tcgcsv-Preisarchiv
│   ├── build_indices.py       Berechnung SPK500 + SPKS, erzeugt site/data/
│   ├── export_pricecharting.py  einmaliger Export der PriceCharting-Bestände
│   └── send_newsletter.py     Wochenbericht erstellen + versenden
├── data/
│   ├── daily/JJJJ-MM-TT.csv.gz  ein Preistag pro Datei (git-freundlich)
│   └── products.csv.gz        Produkt-Stammdaten
└── site/                      die fertige Website (wird von Pages ausgeliefert)
    ├── index.html · app.js · style.css
    ├── data/                  von build_indices/export erzeugte Daten
    └── newsletter/            Archiv der Wochenberichte
```

## Hosting: GitHub Pages + Actions (0 €)

Einmalige Einrichtung, danach läuft alles von selbst:

1. **GitHub-Konto** (falls noch keins): https://github.com/signup
2. **Neues Repository** anlegen: https://github.com/new → Name z. B.
   `pokeindex`, Sichtbarkeit **Public** (nötig für kostenloses Pages).
   Keine Haken bei README/gitignore setzen.
3. **Diesen Ordner hochladen.** Im Ordner `Pokemon Index und Website` eine
   Konsole öffnen (Windows: Adresszeile → `cmd`) und – mit deinem
   Benutzernamen statt `DEINNAME` – ausführen:

   ```bat
   git init
   git add .
   git commit -m "PokeIndex initial"
   git branch -M main
   git remote add origin https://github.com/DEINNAME/pokeindex.git
   git push -u origin main
   ```

   (Git für Windows: https://git-scm.com/download/win – beim Push mit dem
   Browser anmelden.)
4. **Pages aktivieren:** Repo → Settings → Pages → „Source" auf
   **GitHub Actions** stellen.
5. **Secrets für den Newsletter:** Repo → Settings → Secrets and variables →
   Actions → „New repository secret":
   - `GMAIL_ADDRESS` = deine Gmail-Adresse
   - `GMAIL_APP_PASSWORD` = ein Gmail-**App-Passwort** (nicht dein normales
     Passwort). Erstellen: https://myaccount.google.com/apppasswords
     (setzt aktivierte 2-Faktor-Authentifizierung voraus; App-Name egal,
     das 16-stellige Passwort ohne Leerzeichen eintragen)
   - optional `NEWSLETTER_TO` = abweichende Empfängeradresse
6. **Ersten Lauf starten:** Repo → Actions → „Täglicher Datenabzug + Deploy" →
   „Run workflow". Danach ist die Seite unter
   `https://DEINNAME.github.io/pokeindex/` erreichbar (Handy: Seite öffnen →
   „Zum Startbildschirm hinzufügen").

Ab dann automatisch: täglich 20:30 UTC Daten + Deploy; alle paar Stunden
Backfill der Historie bis zurück zum 08.02.2024 (dauert einige Tage, der
Chart wächst dabei rückwärts); sonntags 07:00 UTC der Newsletter.

## Lokal ausführen (optional)

```bat
pip install -r requirements.txt
python scripts/fetch_prices.py          :: Tagespreise ziehen
python scripts/backfill_archive.py --days 30
python scripts/build_indices.py         :: Indizes + Website-Daten
python scripts/send_newsletter.py --dry-run
```

Danach `site/index.html` im Browser öffnen. Der PriceCharting-Export muss nur
einmal laufen (bzw. wenn du neu gescrapt hast):

```bat
python scripts/export_pricecharting.py --karten "..\karten.sqlite3" --sealed "..\sealed.sqlite3"
```

## Regeln der Indizes (Kurzfassung)

- Preis je Produkt = TCGplayer **Market Price** des wertvollsten regulären
  Printings (1st Edition ausgeschlossen), täglich via tcgcsv.com.
- **Carry-Forward:** fehlender Preis wird bis 70 Tage fortgeschrieben (†).
- **Ausreißer-Guard:** Abweichung >2,5× / <0,4× vom Median der letzten 14
  bestätigten Preise wird gehalten, bis ein zweiter Tag sie bestätigt.
- Tages-/Wochenänderungen nur zwischen **bestätigten** Preisen.
- Mitglieder = Top 500 nach Preis, täglich fortgeschrieben; Indexstand bleibt
  bei Mitgliederwechseln stetig (Divisor-Logik), Start 1000.
- Alle Parameter stehen in `scripts/common.py` und lassen sich anpassen;
  die Historie wird bei jedem Lauf komplett neu gerechnet, Änderungen wirken
  also rückwirkend konsistent.

## Kosten & Grenzen

- GitHub Free: Actions-Minuten (öffentliches Repo: unbegrenzt) und Pages
  reichen locker; Gmail-Versand an dich selbst ist kostenlos.
- tcgcsv.com ist ein Community-Projekt – der tägliche Abzug (~450 Anfragen)
  ist ausdrücklich erlaubt; bitte nicht öfter als nötig laufen lassen.
- Die Seite ist öffentlich erreichbar, aber ohne Suchmaschinen-Indexierung
  (`noindex`) und ohne Verlinkung praktisch nur für dich auffindbar.
