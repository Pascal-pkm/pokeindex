# PokéIndex – privates Multi-Asset-Dashboard

Eigenes Dashboard für Sammlermärkte, erweitert auf alle Anlageklassen der
Masterarbeit – mit täglicher Datenerhebung, Indexberechnung, Risikoanalytik,
Screening samt Backtest und einer privaten Portfolio-Bewertung.

- **SPK500** – Top 500 Pokémon-Einzelkarten (TCGplayer Market Price, täglich)
- **SPKS** – Sealed-Index, gleiche Regeln (täglich)
- **CS2500** – Top 500 CS2-Skins (Skinport, täglich) plus gleichgewichteter
  Index nach Masterarbeits-Methodik (Steam-Historie seit 2014, täglich fortgeführt)
- **Märkte** – S&P 500, DAX, NASDAQ 100, EuroStoxx 50, MSCI World, Gold, Silber,
  Bitcoin (Historie 2013–2026, täglich fortgeschrieben; Yahoo + Stooq)
- **Risiko** – Volatilität, Drawdown, Sharpe/Sortino, Korrelation und Beta
  gegenüber klassischen Anlagen; zusätzlich die Verteilung der
  Einzelprodukt-Volatilität
- **Potenziale** – Long-only-Screening auf tagesaktuellen Reihen, mit
  Backtest (Information Coefficient, Quintile, Netto-Strategiekurve)
- **Bestände** – PriceCharting-Scrapes (≈25.000 Karten, ≈1.850 Sealed) und
  Steam-Market-Scrapes (≈13.700 CS2-Items) mit monatlicher Historie
- **Portfolio** (lokal, nicht öffentlich) – echtes Order Book → Bewertung,
  P&L brutto/netto, zeitgewichtete Rendite, Benchmarkvergleich

## Architektur

Die Fachlogik liegt in **einem** Paket, das alle Konsumenten teilen. Vor der
Konsolidierung existierten Klassifikation, Ausreißerbehandlung, Forward-Fill und
Indexlogik in drei abweichenden Fassungen (Wurzel-Scraper, diese Pipeline,
Sealed-Dashboard) – dieselbe Frage lieferte je nach Pfad drei Antworten.

```
Pokemon Index und Website/
├── pokedata/                  ← gemeinsame Bibliothek (Quelle der Wahrheit)
│   ├── atomicio.py            atomare Datei-/Gzip-/JS-Schreiber
│   ├── classify.py            Sealed-Klassifikation für Namen UND Slugs
│   ├── indexlib.py            Guard, Carry-Forward, Top-N-Kette, EW-Index
│   ├── quality.py             Validierung (Lücken, Drift, Plausibilität)
│   ├── risk.py                Vola, Drawdown, Sharpe, Korrelation, Beta
│   ├── fees.py                Transaktionskostenmodell je Handelsplatz
│   ├── screen.py              Potenzial-Screening (Günstigkeit/Stabilität)
│   ├── backtest.py            Event-Study, IC, Quintile, Strategiekurve
│   ├── portfolio.py           Order-Book-Ingest, Bewertung, P&L, TWR
│   ├── names.py               deutsch-englische Namensbrücke
│   ├── fx.py                  EZB-Tageskurse USD/EUR mit lokalem Cache
│   └── sources/               tcgcsv · skinport · markets · pricecharting
├── scripts/                   nur Verdrahtung, keine Fachlogik
│   ├── fetch_prices.py        täglicher Abzug (tcgcsv)
│   ├── fetch_cs2.py           täglicher CS2-Abzug (Skinport)
│   ├── fetch_markets.py       Marktdaten (Yahoo, Fallback Stooq)
│   ├── backfill_archive.py    Historie aus dem tcgcsv-Preisarchiv
│   ├── build_indices.py       SPK500 · SPKS · CS2500 · Märkte
│   ├── build_risk.py          Risiko- und Korrelationskennzahlen
│   ├── build_screening.py     Screening (+ --backtest)
│   ├── build_portfolio.py     LOKAL: Portfolio-Bewertung
│   ├── validate_data.py       Wächter (mit --strict im Workflow)
│   ├── export_pricecharting.py  Bestände → Website
│   ├── send_newsletter.py     Tages-/Wochenbericht
│   └── notify_failure.py      Fehler-Mail für Actions
├── tests/                     Golden Master + Unit-Tests
├── data/                      Tagesdateien, Stammdaten, FX-Cache
└── site/                      statische Website (GitHub Pages)
```

## Betrieb (automatisch)

| Workflow | Zeitpunkt | Inhalt |
|---|---|---|
| `daily.yml` | 20:30 UTC | Selbsttest → Preise (Karten, CS2, Märkte) → Backfill → Indizes → Risiko → Screening → **Validierung (strict)** → Newsletter → Commit → Pages |
| `backfill.yml` | 02:15 / 08:15 / 14:15 UTC | Archivtage nachladen, neu rechnen, validieren, deployen |
| `newsletter.yml` | So 07:00 UTC | Datenstand prüfen, Wochenbriefing versenden |
| `ci.yml` | bei jedem Push | ruff + pytest + Rauchtest der Pipeline |

Jeder Workflow schickt bei Fehlschlag eine E-Mail (`notify_failure.py`) – vorher
fiel ein roter Lauf nur auf, wenn man von sich aus nachschaute.

## Lokal ausführen

```bat
pip install -r requirements.txt
python -m pytest tests -q                     :: Selbsttest (inkl. Golden Master)
python scripts/fetch_prices.py                :: Tagespreise
python scripts/backfill_archive.py --days 30
python scripts/build_indices.py               :: Indizes + Website-Daten
python scripts/build_risk.py                  :: Risikokennzahlen
python scripts/build_screening.py --backtest  :: Screening + Validierung
python scripts/validate_data.py               :: Datenprüfung
python scripts/send_newsletter.py --mode daily --dry-run
```

Website danach mit `site/index.html` öffnen. Der PriceCharting-Export läuft nur
nach einem neuen Scrape:

```bat
python scripts/export_pricecharting.py --karten "..\karten.sqlite3" --sealed "..\sealed.sqlite3"
```

### Portfolio (privat, bleibt lokal)

```bat
python scripts/build_portfolio.py             :: Bericht + Excel im Projektordner
python scripts/build_portfolio.py --map-only  :: nur Zuordnung aktualisieren
```

Erzeugt `Portfolio_Bericht.html`, `Portfolio_Analyse.xlsx`, `portfolio.json` sowie
zwei editierbare Dateien **eine Ebene über dem Repository**:

- `portfolio_map.csv` – Zuordnung deutscher Artikel zu englischen TCGplayer-
  Produkten. Automatische Vorschläge mit Score; Zeilen mit Status `unsicher`
  oder `offen` prüfen und auf `bestaetigt` setzen. Korrekturen bleiben bei
  jedem weiteren Lauf erhalten.
- `portfolio_prices_manual.csv` – optionale echte Cardmarket-Preise in EUR.
  Diese haben **Vorrang** vor dem Proxy und sollten für belastbare Zahlen
  gepflegt werden.

Alle Portfolio-Ausgaben stehen in `.gitignore`: das Repository ist öffentlich,
eigene Kaufpreise und Mengen gehören dort nicht hin.

## Methodik der Indizes

**Preis je Produkt.** TCGplayer **Market Price** des wertvollsten *regulären*
Printings. Ausgeschlossen: „1st Edition" (anderes Gut) und `highPrice`
(„price parking"). Neu: **Printing-Stabilität** – existiert für das Printing des
Vortags ein Marktpreis, wird es beibehalten. Ohne diese Regel wechselt der
Referenzpreis zwischen Holo und Reverse Holo und erzeugt Scheinrenditen.

**Speichergrenze mit Hysterese.** Einzelkarten werden ab 25 USD aufgenommen und
bis 15 USD gehalten (Sealed immer). Vorher fielen Karten beim Unterschreiten von
25 USD aus den Daten – die Zensur entfernt genau die Verlierer und verzerrt
Ranking und Basket nach oben.

**Bereinigung (nur Anzeige, Ranking, Mitgliederauswahl):**
- *Ausreißer-Guard*: > 2,5× oder < 0,4× des Medians der letzten 14 bestätigten
  Preise wird auf dem Median gehalten, bis ein zweiter Tag den Wert bestätigt.
- *Carry-Forward*: fehlender Preis wird bis 70 Kalendertage fortgeschrieben (†).
- Tages-/Wochenänderungen werden nur zwischen **bestätigten** Preisen gezeigt.

**Indexbewegung.** Winsorisierter (1 %/99 %) **gleichgewichteter** Mittelwert der
Tagesrenditen der gestrigen Mitglieder, gemessen an **rohen** Preispaaren.
Renditepaare mit gewechseltem Printing werden verworfen (Printing-Guard). Liegen
weniger als **20 % der Indexgröße** valide Paare vor (100 von 500), bleibt das
Niveau unverändert. Startniveau 1000.

> **Korrektur gegenüber der früheren Dokumentation:** Hier wird **kein
> Divisor-Verfahren** verwendet. Die frühere README beschrieb eine
> „Divisor-Logik", implementiert war immer ein verketteter, gleichgewichteter
> Renditeindex. Der Kettenansatz ist bei täglich wechselnden Mitgliedern das
> robustere Verfahren; die Beschreibung war falsch, nicht der Code.

**CS2.** Monatliche Steam-Vorgeschichte (Top 500, ab 2014-06, Mindestbreite 50
Items) wird an den täglichen Skinport-Index verkettet. Der Quellenbruch ist im
Datenmodell als `splice` hinterlegt: Steam liefert **Verkaufspreise**, Skinport
**Angebotsmediane (Ask)**; zwischen letztem Monats- und erstem Tagespunkt liegt
eine Erhebungslücke, die ausgewiesen und nicht modelliert wird.

**Determinismus.** Die komplette Historie wird bei jedem Lauf neu gerechnet; es
gibt keinen persistenten Zwischenstand, der kaputtgehen kann. Alle Parameter
stehen in `scripts/common.py` bzw. `pokedata/indexlib.py::IndexRules`.

**Golden Master.** `tests/golden/legacy_levels.json` hält die Indexstände von
vor der Konsolidierung fest. Der Test belegt, dass die neue Bibliothek mit
`LEGACY_RULES` exakt dieselben Werte reproduziert (SPK500 1596,24 /
SPKS 2603,67 zum 17.07.2026) – Methodikänderungen sind dadurch von
Refaktorierungsfehlern unterscheidbar.

## Risikokennzahlen – und ihre Grenze

Volatilität wird aus **abstandsskalierten** Renditen (`r / √Tage`) berechnet.
Das ist notwendig, weil die CS2-Reihe Monats- und Tagespunkte mischt; eine
naive Annualisierung mit √365 ergab dreistellige Scheinvolatilitäten.

**Wichtige Einschränkung:** Die Index-Volatilität ist strukturell zu niedrig.
Ein gleichgewichteter Index aus 500 Positionen mittelt idiosynkratische
Schwankungen weg, Carry-Forward glättet zusätzlich. Sharpe Ratios über 3 sind
ein Artefakt dieser Glättung, keine Anlageeigenschaft. Für die Beurteilung
einzelner Käufe zeigt die Website deshalb die **Einzelprodukt-Volatilität**
(Median über 12 Monate: Karten ≈ 30 %, Sealed ≈ 17 % p. a.).

## Screening und was der Backtest zeigt

Das Screening bewertet je Produkt **Günstigkeit** (Position in der eigenen
Preisspanne, Abschlag zum Allzeithoch, Abstand unter dem Mittel) und
**Stabilität** (niedrige Volatilität, lange Konsolidierung im ±10-%-Band,
flacher Trend, niedriger Variationskoeffizient), jeweils als Perzentilrang im
Querschnitt.

`build_screening.py --backtest` prüft diese Signale gegen die Zukunft
(Look-ahead-frei, Forward-Renditen über 30/90/180 Tage, Round-Trip-Gebühren aus
`fees.py`). Ergebnis im Zeitraum 2024-02 bis 2026-07:

| Signal | IC (90 T) | t | Überschuss netto |
|---|---|---|---|
| Momentum (Sealed) | +0,11 | 4,7 | −5,7 pp |
| Stabilität (Sealed) | −0,08 | −3,7 | −8,8 pp |
| **Potenzial (Sealed)** | **−0,20** | **−6,9** | **−9,8 pp** |
| Günstigkeit (Sealed) | −0,24 | −7,5 | −9,9 pp |

**Lesart:** Das „günstig & stabil"-Signal war in diesem Zeitraum *negativ*
prädiktiv – wer nach Günstigkeit kaufte, blieb systematisch hinter dem
gleichgewichteten Markt zurück (Sealed insgesamt +102 % über den Zeitraum). Der
Markt belohnte Momentum, nicht Mean-Reversion. Das Screening bleibt als
Recherche-Filter nützlich (es findet konsolidierende, wenig gelaufene Produkte),
ist aber **kein** validiertes Kaufsignal. Einschränkungen: nur ein Marktregime
(starker Aufwärtsmarkt), überlappende Halteperioden, Marktpreis-Schätzer statt
ausgeführter Trades.

## Kostenmodell

`pokedata/fees.py`, Stand Juli 2026, alle Sätze als Parameter:
Cardmarket ≈ 5 % Provision + ~1 % Zahlungsabwicklung; eBay.de (privat) 11 % bis
1.990 € plus 0,35 € Fixgebühr; Amazon.de 15 %. Nettowerte und Break-even-Preise
beziehen sich immer auf den angenommenen **Verkaufskanal** (Standard Cardmarket),
nicht auf den Kaufkanal.

## Datenqualität

`validate_data.py` prüft vor jedem Deploy: Lücken in den Tagesreihen,
Zeilenzahl-Drift gegen den Median der Vortage (>50 % Rückgang = Fehler),
Preisplausibilität, Duplikate, Alter aller Reihen, Sortierung und Eindeutigkeit
der Indexzeitreihen. Ergebnis liegt als `site/data/quality.json` bei. Der
tägliche Workflow bricht bei Fehlern ab, statt einen kaputten Stand zu
veröffentlichen.

Alle Schreibvorgänge sind **atomar** (Temp-Datei + `os.replace`): ein Abbruch
mitten im Schreiben kann keine halbe Gzip-Datei hinterlassen. Gzip-Ausgaben sind
zudem deterministisch (`mtime=0`, kein Dateiname im Header) – gleicher Inhalt
erzeugt keinen Git-Diff.

## Kosten & Grenzen

- GitHub Free: Actions-Minuten (öffentliches Repo unbegrenzt) und Pages reichen;
  Gmail-Versand an sich selbst ist kostenlos.
- tcgcsv.com ist ein Community-Projekt – der tägliche Abzug (~450 Anfragen) ist
  ausdrücklich erlaubt; nicht häufiger laufen lassen als nötig.
- Vor 2024-02-08 existieren keine archivierten TCGplayer-Preise.
- Preise sind Marktpreis-Schätzer bzw. Angebotsmediane, keine realisierten
  Transaktionen. Spread, Liquidität und Gebühren sind separat modelliert.
- Die Seite ist öffentlich erreichbar, aber `noindex` und unverlinkt.

**Disclaimer:** Historische Wertentwicklung ist keine Prognose. Analyse- und
Screening-Werkzeug, keine Anlageberatung.
