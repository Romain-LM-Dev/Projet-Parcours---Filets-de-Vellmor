<#
.SYNOPSIS
  Démarre FILETS : le moteur (en « salon »), Godot, et au choix Kafka avec ses services, Ollama.

.DESCRIPTION
  Par défaut, le moteur ouvre un salon et attend : on règle la partie (mode, saisons, pêcheurs, moteur d'IA…) dans le
  menu de démarrage de Godot, puis on la lance quand on veut. Pause, vitesse, changement de mode et arrêt se pilotent
  depuis la barre du haut de Godot.

  - Sans -Kafka : `python -m filets serve` (le moteur ouvre lui-même le pont vers Godot).
  - Avec -Kafka : démarre le broker (docker compose), les services indicators / store / bridge chacun dans sa fenêtre,
    puis le moteur `--bus kafka` ici (le service bridge ouvre le port 8765, pas le moteur).
  - Avec -Ollama : vérifie le serveur et les modèles, et présélectionne Ollama dans le menu. Par défaut le réglage
    « rapide » (Qwen 2.5 3B + 1,5B, qui tiennent ensemble dans 6 Go de mémoire graphique) ; -OllamaProfile quality
    choisit le 7B (meilleur, mais bien plus lent : chaque changement de modèle coûte une trentaine de secondes).
  - Avec -Auto : ancien comportement, sans menu : la partie démarre tout de suite (`python -m filets run`).
  Ctrl+C arrête le moteur ; .\stop.ps1 ferme aussi les services Kafka et le broker.

.PARAMETER Kafka      Utilise Kafka (Docker Desktop doit être lancé).
.PARAMETER Ollama     Vérifie Ollama et le présélectionne dans le menu (ou le fait utiliser avec -Auto).
.PARAMETER OllamaProfile  fast (3B + 1,5B, défaut) ou quality (7B + 1,5B), avec -Ollama.
.PARAMETER NoGodot    Ne lance pas Godot.
.PARAMETER NoEngine   Ne lance pas le moteur : à utiliser quand il tourne déjà (services ou Godot fermés par erreur, une partie
                      est en cours) ; relance les services Kafka et Godot, qui se rattachent à la partie en cours.
.PARAMETER Ui         Avec -Kafka : ajoute l'interface web Kafka UI sur http://localhost:8080.
.PARAMETER Auto       Lance une partie immédiatement, sans passer par le menu.
.PARAMETER Mode       sync ou async : mode proposé par défaut dans le menu (ou utilisé avec -Auto).
.PARAMETER Agents     Nombre de pêcheurs de la composition de base.
.PARAMETER Seasons    Nombre de saisons proposé par défaut.
.PARAMETER Config     Configuration YAML de base (défaut : config/default.yaml).
.PARAMETER GodotPath  Chemin de l'exécutable Godot (sinon : GODOT_PATH, ou le fichier godot.path, ou le PATH).
.PARAMETER Extra      Arguments supplémentaires pour le moteur, ex. --set time.sim_hours_per_second=1

.EXAMPLE
  .\start.ps1
  .\start.ps1 -Kafka -Ollama
  .\start.ps1 -Mode async -Agents 12
  .\start.ps1 -Auto -Mode sync -Seasons 5
#>
[CmdletBinding(PositionalBinding = $false)]   # sans cela, « --set x=y » serait lié à -Config au lieu d'aller dans -Extra
param(
    [switch]$Kafka,
    [switch]$Ollama,
    [ValidateSet('fast', 'quality')][string]$OllamaProfile = 'fast',
    [switch]$NoGodot,
    [switch]$NoEngine,
    [switch]$Ui,
    [switch]$Auto,
    [ValidateSet('sync', 'async')][string]$Mode = 'sync',
    [string]$Config,
    [int]$Agents,
    [int]$Seasons,
    [string]$GodotPath,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Extra
)

# 'Continue' : en Windows PowerShell 5.1, une commande native qui écrit sur stderr lèverait une exception avec 'Stop'.
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pidFile    = Join-Path $PSScriptRoot '.filets-services.pids'
$WsPort     = 8765
# « fast » : les deux modèles tiennent ensemble dans 6 Go, donc aucun échange ; « quality » : le 7B prend presque toute la carte.
if ($OllamaProfile -eq 'quality') {
    $OllamaModels = @('qwen2.5:7b', 'qwen2.5:1.5b'); $OllamaLlm = 'ollama'; $OllamaConfig = 'config/ollama.yaml'
} else {
    $OllamaModels = @('qwen2.5:3b', 'qwen2.5:1.5b'); $OllamaLlm = 'ollama_fast'; $OllamaConfig = 'config/ollama_fast.yaml'
}

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "    [x]  $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $venvPython)) { Fail "Environnement introuvable : lance d'abord .\install.ps1" }

# Un « -- » éventuel (séparateur) ne doit pas être transmis à filets.
$Extra = @($Extra | Where-Object { $_ -and $_ -ne '--' })

# --- Le port du pont doit être libre : un ancien moteur ou un ancien pont l'occuperait --------------------------
$busy = Get-NetTCPConnection -LocalPort $WsPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($busy) {
    $who = (Get-Process -Id $busy.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Fail "Le port $WsPort est déjà utilisé (processus $who, PID $($busy.OwningProcess)) : un ancien moteur ou pont tourne encore. Lance .\stop.ps1, ou ferme-le, puis relance."
}

# --- Ollama --------------------------------------------------------------------------------------------------
if ($Ollama) {
    Step 'Ollama'
    $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollamaExe) {
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path $candidate) { $ollamaExe = $candidate }
    }
    if (-not $ollamaExe) { Fail "Ollama est introuvable. Lance .\install.ps1 -InstallMissing (ou installe-le depuis https://ollama.com/download)." }

    # 127.0.0.1 et non « localhost » : Ollama n'écoute qu'en IPv4, et Windows PowerShell 5.1 essaie d'abord ::1, ce qui peut
    # faire expirer la sonde (le serveur semble alors absent alors qu'il répond).
    function Get-OllamaTags {
        try { return (Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5).models.name } catch { return $null }
    }
    $tags = Get-OllamaTags
    if ($null -eq $tags) {
        Write-Host '    Démarrage du serveur Ollama...'
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden
        for ($i = 0; $i -lt 30 -and $null -eq $tags; $i++) { Start-Sleep -Seconds 1; $tags = Get-OllamaTags }
    }
    if ($null -eq $tags) { Fail 'Le serveur Ollama ne répond pas sur localhost:11434.' }
    Ok 'serveur Ollama à l''écoute'
    foreach ($m in $OllamaModels) {
        if ($tags -contains $m) { Ok "modèle $m présent" }
        else {
            Write-Host "    ollama pull $m"
            & $ollamaExe pull $m
            if ($LASTEXITCODE -ne 0) { Fail "Impossible de télécharger $m." }
        }
    }
}

# --- Kafka ---------------------------------------------------------------------------------------------------
if ((Test-Path $pidFile) -and -not $NoEngine) { Remove-Item $pidFile -Force }
if ($Kafka) {
    Step 'Kafka'
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'Docker est introuvable (installe Docker Desktop).' }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop n'est pas démarré : lance-le, attends qu'il soit prêt, puis relance." }

    if ($Ui) { docker compose --profile ui up -d } else { docker compose up -d }
    if ($LASTEXITCODE -ne 0) { Fail 'docker compose up a échoué.' }

    Write-Host '    Attente du broker sur localhost:9092 (jusqu''à 90 s)...'
    $probe = "from confluent_kafka.admin import AdminClient; AdminClient({'bootstrap.servers':'localhost:9092'}).list_topics(timeout=3)"
    $ready = $false
    for ($i = 0; $i -lt 30 -and -not $ready; $i++) {
        & $venvPython -c $probe *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true } else { Start-Sleep -Seconds 3 }
    }
    if (-not $ready) { Fail 'Le broker Kafka ne répond pas. Vérifie avec : docker compose ps  /  docker compose logs kafka' }
    Ok 'broker Kafka prêt (localhost:9092)'
    if ($Ui) { Ok 'Kafka UI : http://localhost:8080' }

    Step 'Services (indicators, store, bridge)'
    $shell = (Get-Process -Id $PID).Path   # powershell.exe (ou pwsh.exe), le même que celui-ci
    foreach ($svc in @('indicators', 'store', 'bridge')) {
        $cmd = "`$Host.UI.RawUI.WindowTitle = 'FILETS - $svc'; & '$venvPython' -m filets.services.$svc"
        $p = Start-Process -FilePath $shell -WorkingDirectory $PSScriptRoot -PassThru `
             -ArgumentList @('-NoProfile', '-NoExit', '-Command', $cmd)
        Add-Content -Path $pidFile -Value $p.Id
        Ok "service $svc lancé (fenêtre PID $($p.Id))"
    }
    Start-Sleep -Seconds 3
}

# --- Godot ---------------------------------------------------------------------------------------------------
if (-not $NoGodot) {
    Step 'Godot'
    $godotExe = $GodotPath
    if (-not $godotExe) { $godotExe = $env:GODOT_PATH }
    $pathFile = Join-Path $PSScriptRoot 'godot.path'
    if (-not $godotExe -and (Test-Path $pathFile)) { $godotExe = (Get-Content $pathFile -TotalCount 1).Trim() }
    if (-not $godotExe) { $godotExe = (Get-Command godot*, Godot* -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
    if (-not $godotExe -or -not (Test-Path $godotExe)) {
        Warn 'Godot introuvable (passe -GodotPath, définis GODOT_PATH, ou écris son chemin dans le fichier godot.path).'
        Warn 'Ouvre godot\project.godot à la main, puis F5 : le menu de démarrage s''affichera.'
    } else {
        $godotDir = Join-Path $PSScriptRoot 'godot'
        if (-not (Test-Path (Join-Path $godotDir '.godot'))) {
            Write-Host '    Premier import du projet Godot...'
            & $godotExe --headless --path $godotDir --import *> $null
        }
        # Godot réessaie de se connecter toutes les 2 s : inutile d'attendre le moteur.
        # Guillemets explicites : Start-Process (PS 5.1) ne protège pas les chemins contenant des espaces.
        Start-Process -FilePath $godotExe -ArgumentList @('--path', "`"$godotDir`"")
        Ok 'Godot lancé'
    }
}

# --- Moteur --------------------------------------------------------------------------------------------------
if ($NoEngine) {
    Write-Host "`nServices et Godot (re)lancés ; le moteur n'a pas été touché. .\stop.ps1 arrête tout." -ForegroundColor Green
    exit 0
}
if ($Auto) {
    Step 'Partie immédiate (sans menu)'
    if (-not $Config) { $Config = if ($Ollama) { $OllamaConfig } else { 'config/default.yaml' } }
    $engineArgs = @('-m', 'filets', 'run', '--config', $Config, '--mode', $Mode)
    if ($Kafka) { $engineArgs += @('--bus', 'kafka') } else { $engineArgs += '--ws' }
} else {
    Step 'Moteur (salon)'
    if (-not $Config) { $Config = 'config/default.yaml' }
    $engineArgs = @('-m', 'filets', 'serve', '--config', $Config, '--mode', $Mode)
    if ($Kafka)  { $engineArgs += @('--bus', 'kafka') }
    if ($Ollama) { $engineArgs += @('--llm', $OllamaLlm) }
}
if ($PSBoundParameters.ContainsKey('Agents'))  { $engineArgs += @('--agents',  $Agents) }
if ($PSBoundParameters.ContainsKey('Seasons')) { $engineArgs += @('--seasons', $Seasons) }
if ($Extra) { $engineArgs += $Extra }

Write-Host ("    python " + ($engineArgs -join ' ')) -ForegroundColor DarkGray
if ($Kafka) { Write-Host '    (le service bridge ouvre ws://localhost:8765 ; le moteur n''ouvre pas de port)' -ForegroundColor DarkGray }
if (-not $Auto) { Write-Host '    Règle ta partie dans Godot, puis clique sur « Démarrer la partie ». Ctrl+C ici pour quitter.' -ForegroundColor DarkGray }

# Le moteur tourne dans cette console ; son PID est noté pour que stop.ps1 puisse l'arrêter depuis une autre.
$quoted = $engineArgs | ForEach-Object { if ("$_" -match '\s') { "`"$_`"" } else { "$_" } }
$engine = Start-Process -FilePath $venvPython -ArgumentList $quoted -WorkingDirectory $PSScriptRoot -NoNewWindow -PassThru
Add-Content -Path $pidFile -Value $engine.Id
try {
    $engine.WaitForExit()
    $code = $engine.ExitCode
} finally {
    if (-not $engine.HasExited) { Stop-Process -Id $engine.Id -Force -ErrorAction SilentlyContinue }
    # le moteur est terminé : son numéro ne doit pas rester dans le fichier (il pourrait être réattribué)
    if (Test-Path $pidFile) {
        $left = @(Get-Content $pidFile | Where-Object { $_ -ne "$($engine.Id)" })
        if ($left.Count) { Set-Content -Path $pidFile -Value $left } else { Remove-Item $pidFile -Force }
    }
}

if ($Kafka) {
    Write-Host "`nMoteur arrêté. Les services Kafka tournent encore : .\stop.ps1 pour tout arrêter." -ForegroundColor Yellow
}
exit $code
