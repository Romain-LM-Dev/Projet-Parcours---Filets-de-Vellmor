<#
.SYNOPSIS
  Arrête ce que start.ps1 a lancé : le moteur, les services Kafka, puis les conteneurs (Kafka, et PostgreSQL et le
  stockage objet s'ils tournent).

.PARAMETER KeepKafka
  Laisse les conteneurs tourner (ferme seulement le moteur et les fenêtres de services).

.PARAMETER Purge
  Supprime aussi les données Kafka (volume kafka-data). La base PostgreSQL et le stockage objet sont toujours gardés.
#>
[CmdletBinding()]
param(
    [switch]$KeepKafka,
    [switch]$Purge
)

$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot
$pidFile = Join-Path $PSScriptRoot '.filets-services.pids'

if (Test-Path $pidFile) {
    foreach ($id in Get-Content $pidFile) {
        if ($id -notmatch '^\d+$') { continue }
        # Un numéro de processus peut avoir été réattribué depuis : on ne ferme que ce qui est bien FILETS.
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -match 'filets|FILETS') {
            taskkill /PID $id /T /F *> $null   # /T : ferme aussi le processus Python enfant
            Write-Host "Processus $id arrêté."
        }
    }
    Remove-Item $pidFile -Force
} else {
    Write-Host 'Aucun processus enregistré.'
}

# Filet de sécurité : un moteur ou un service FILETS lancé à la main (donc absent du fichier) garderait le port 8765.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '\s-m\s+filets(\s|\.services\.)' } |
    ForEach-Object {
        taskkill /PID $_.ProcessId /T /F *> $null
        Write-Host "Processus FILETS $($_.ProcessId) arrêté."
    }

if (-not $KeepKafka -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        # jamais « down -v » : il effacerait aussi les volumes de PostgreSQL et du stockage objet
        docker compose --profile ui --profile data down
        if ($Purge) {
            $project = (docker compose config --format json | ConvertFrom-Json).name
            docker volume rm "${project}_kafka-data" *> $null
            Write-Host 'Données Kafka supprimées (PostgreSQL et stockage objet gardés).'
        }
    } else {
        Write-Host "Docker n'est pas démarré : rien à arrêter côté Kafka."
    }
}
