# -*- coding: utf-8 -*-
"""pokedata – gemeinsame Bibliothek des Projekts.

Ein Regelwerk für alle Konsumenten (Website-Pipeline, Newsletter, Sealed-
Dashboard, Scraper). Vor der Konsolidierung existierten dieselben Konzepte
(Klassifikation, Ausreißerbehandlung, Forward-Fill, Indexlogik) in drei
abweichenden Implementierungen; dieses Paket ist die einzige Quelle der
Wahrheit.

Module
------
atomicio     atomare Datei-/Gzip-/JS-Schreiber (kein halb geschriebener Output)
classify     Sealed-Klassifikation für Namen UND URL-Slugs, ein Regelwerk
indexlib     Ausreißer-Guard, Carry-Forward, Top-N-Kettenindex, EW-Index
quality      Datenvalidierung: Lücken, Zeilenzahl-Drift, Preis-Sanity, Zensur
fx           EZB-Tagesreferenzkurse (frankfurter.dev) mit lokalem Cache
fees         Transaktionskostenmodell je Handelsplatz
risk         Vola, Drawdown, Sharpe, Korrelation, rollierende Kennzahlen
portfolio    Order-Book-Ingest, Bewertung, P&L, zeitgewichtete Rendite
backtest     Forward-Return-Auswertung von Screening-Signalen
sources.*    Quell-Clients: tcgcsv, skinport, markets, pricecharting
"""

__version__ = "2.0.0"

# Schema-/Methodikversion. Wird in generierte Artefakte geschrieben, damit
# Auswertungen nachvollziehbar einer Regelfassung zugeordnet werden können.
METHOD_VERSION = "2026-07-26"
