# sync.ps1 - Aendert/committet/pusht deine lokalen Aenderungen und loest den
# haeufigen "non-fast-forward"-Fehler automatisch auf, der entsteht, weil die
# GitHub-Actions-Bots (daily.yml, backfill.yml, newsletter.yml) selbststaendig
# in den Repo committen.
#
# Benutzung: im Repo-Ordner ausfuehren, z. B.
#   .\sync.ps1 "Meine Aenderung"
# Ohne Nachricht wird ein Standardtext verwendet.

param(
    [string]$Message = "Update $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
)

function Fail($msg) {
    Write-Host "ABBRUCH: $msg" -ForegroundColor Red
    exit 1
}

# 1) Lokale Aenderungen sichern
git add -A
git commit -m "$Message" -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "(nichts Neues zu committen, mache trotzdem weiter)" -ForegroundColor Yellow
}

# 2) Vom Server holen und automatisch mergen
git pull --no-rebase --no-edit
if ($LASTEXITCODE -eq 0) {
    Write-Host "Pull sauber gemergt." -ForegroundColor Green
} else {
    # Konfliktdateien ermitteln
    $conflicts = git diff --name-only --diff-filter=U
    if (-not $conflicts) { Fail "Pull fehlgeschlagen, aber keine erkennbaren Konflikte. Bitte 'git status' pruefen." }

    Write-Host "Konflikte gefunden, loese automatisch auf:" -ForegroundColor Yellow
    foreach ($f in $conflicts) {
        if ($f -match '^(scripts/|\.github/)') {
            # Code-/Workflow-Dateien: meine lokale Version gewinnt
            git checkout --ours -- "$f"
            Write-Host "  eigene Version behalten: $f"
        } else {
            # Generierte Daten/Website-Dateien: Server-Version gewinnt
            # (wird beim naechsten automatischen Lauf ohnehin neu berechnet)
            git checkout --theirs -- "$f"
            Write-Host "  Server-Version uebernommen: $f"
        }
        git add -- "$f"
    }
    git commit --no-edit -q
    if ($LASTEXITCODE -ne 0) { Fail "Merge-Commit fehlgeschlagen. Bitte Screenshot schicken." }
    Write-Host "Konflikte automatisch geloest." -ForegroundColor Green
}

# 3) Hochladen
git push
if ($LASTEXITCODE -eq 0) {
    Write-Host "Fertig, alles hochgeladen." -ForegroundColor Green
} else {
    Fail "Push fehlgeschlagen. Bitte Screenshot schicken."
}
