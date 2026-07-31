#!/usr/bin/env bash
# Robuster Push für die Bot-Workflows.
#
# Problem, das dieses Skript löst
# ------------------------------
# Drei Workflows (daily, backfill, newsletter) und der Mensch am Rechner
# schreiben in dasselbe Repository. Sie ändern dabei zwangsläufig dieselben
# GENERIERTEN Dateien: site/data/idx_*.js, summary.json, risk.js, screen.js,
# data/markets_raw.csv.gz, die Newsletter-Archive.
#
# Ein einfaches "git pull --rebase" läuft dabei früher oder später in einen
# Konflikt. Ein Bot kann Konflikte aber nicht beantworten: der Rebase bleibt
# stehen, der Runner landet im detached HEAD und der Push scheitert mit
# "fatal: You are not currently on a branch" (Exitcode 128) – genau das ist
# passiert.
#
# Lösung
# ------
# Alle strittigen Dateien sind vollständig aus den Rohdaten ABGELEITET. Es gibt
# also immer eine richtige Antwort: der gerade berechnete Stand dieses Laufs.
# Beim Rebase bezeichnet "theirs" den Commit, der gerade angewendet wird – also
# unseren. `-X theirs` löst damit jeden Konflikt in generierten Dateien
# automatisch und korrekt auf, ohne stehenzubleiben.
#
# Zusätzlich wird bis zu dreimal versucht: zwischen fetch und push kann ein
# paralleler Lauf gepusht haben (Concurrency-Gruppe verhindert das meiste,
# aber nicht alles).
set -uo pipefail

BRANCH="${1:-main}"
VERSUCHE="${2:-3}"

for i in $(seq 1 "$VERSUCHE"); do
  echo "Push-Versuch $i/$VERSUCHE ..."
  git fetch --quiet origin "$BRANCH"

  # Sicherstellen, dass wir auf einem Branch stehen (nach einem früheren
  # Fehlversuch kann der Runner im detached HEAD sein).
  if ! git symbolic-ref -q HEAD >/dev/null; then
    echo "  HEAD ist detached – setze auf $BRANCH zurück"
    git checkout -B "$BRANCH"
  fi

  if git rebase -X theirs "origin/$BRANCH"; then
    if git push origin "HEAD:$BRANCH"; then
      echo "Erfolgreich gepusht (Versuch $i)."
      exit 0
    fi
    echo "  Push abgelehnt – jemand war schneller, neuer Versuch"
  else
    echo "  Rebase fehlgeschlagen – wird zurückgenommen"
    git rebase --abort || true
  fi
  sleep $((5 * i))
done

echo "::error::Push nach $VERSUCHE Versuchen fehlgeschlagen. Der Datenstand"
echo "::error::wurde berechnet, aber nicht veröffentlicht. Nächster Lauf holt es nach."
exit 1
