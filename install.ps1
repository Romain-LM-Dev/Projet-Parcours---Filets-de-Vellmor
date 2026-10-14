<#
.SYNOPSIS
  Installation de FILETS : environnement Python, dépendances, Kafka (image Docker) et modèles Ollama.

.DESCRIPTION
  Suit « FILETS — Démarrer le jeu » (parties 1, 2, 4 et 5). Peut être relancé sans risque.

.PARAMETER InstallMissing
  Installe avec winget ce qui manque (Python 3.13, Docker Desktop, Ollama) sans poser de question.

.PARAMETER SkipKafka
  Ne prépare pas Docker / Kafka.

.PARAMETER SkipOllama
  Ne prépare pas Ollama ni les modèles.

.PARAMETER Quality
  Télécharge aussi qwen2.5:7b (4,7 Go), pour l'option « Ollama · qualité » du menu. Par défaut, seuls les modèles du réglage
  rapide (qwen2.5:3b et qwen2.5:1.5b) sont téléchargés : ils suffisent et tiennent ensemble dans 6 Go de mémoire graphique.

.PARAMETER Open
  Télécharge aussi tev1:0.8b (0,8 Go), le modèle de décision open de l'option « Ollama · rapide + réflexes open » (réflexes
  et bulletins de vote). Il demande Ollama 0.40.4 ou plus ; sans lui, ces décisions passent par qwen2.5:1.5b.

.PARAMETER Data
  Prépare le stockage de config/data.yaml : images Docker de PostgreSQL + pgvector et du stockage objet S3 (SeaweedFS), et
  le modèle de plongement embeddinggemma (0,6 Go) pour le RAG vectoriel.

.PARAMETER SkipTests
  Ne lance pas pytest à la fin.

.PARAMETER GodotPath
  Chemin de l'exécutable Godot : il est mémorisé dans godot.path, et start.ps1 le retrouvera tout seul.

.EXAMPLE
  .\install.ps1
  .\install.ps1 -InstallMissing
#>
[CmdletBinding()]
param(
    [switch]$InstallMissing,
    [switch]$SkipKafka,
    [switch]$SkipOllama,
    [switch]$Quality,
    [switch]$Open,
    [switch]$Data,
    [switch]$SkipTests,
    [string]$GodotPath
)

# 'Continue' : en Windows PowerShell 5.1, une commande native qui écrit sur stderr lèverait une exception avec 'Stop'.
# Les codes de retour ($LASTEXITCODE) sont vérifiés explicitement.
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

# 3B + 1,5B : le réglage rapide (config/ollama_fast.yaml), recommandé sur une carte de 6 Go ; 7B (avec -Quality) : le réglage
# « qualité » (config/ollama.yaml), bien plus lent.
$OllamaModels = @('qwen2.5:3b', 'qwen2.5:1.5b')
if ($Quality) { $OllamaModels += 'qwen2.5:7b' }
if ($Data) { $OllamaModels += 'embeddinggemma' }
$OptionalModels = if ($Open) { @('tev1:0.8b') } else { @() }   # facultatif : Ollama 0.40.4 ou plus
$PythonVersions = @('3.13', '3.12', '3.11', '3.10')   # versions supportées : 3.10 à 3.13

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "    [x]  $msg" -ForegroundColor Red; exit 1 }

function Test-Command($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Install-WithWinget($id, $label) {
    if (-not (Test-Command winget)) { Warn "winget est absent : installe $label à la main."; return $false }
    Write-Host "    Installation de $label via winget..."
    winget install --id $id -e --accept-package-agreements --accept-source-agreements
    return ($LASTEXITCODE -eq 0)
}

function Find-Python {
    # Renvoie la commande (exe + arguments) d'un Python 3.10 à 3.13, ou $null.
    if (Test-Command py) {
        foreach ($v in $PythonVersions) {
            & py "-$v" -c "import sys" 2>$null
            if ($LASTEXITCODE -eq 0) { return @('py', "-$v") }
        }
    }
    foreach ($exe in @('python', 'python3')) {
        if (Test-Command $exe) {
            $ver = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $PythonVersions -contains $ver) { return @($exe) }
        }
    }
    return $null
}

# --- 1. Python et environnement virtuel --------------------------------------------------------
Step 'Python 3.10 à 3.13'
$py = Find-Python
if (-not $py) {
    if ($InstallMissing -and (Install-WithWinget 'Python.Python.3.13' 'Python 3.13')) {
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
        $py = Find-Python
    }
    if (-not $py) {
        Fail "Aucun Python 3.10 à 3.13 trouvé (les versions plus récentes n'ont pas encore toutes les roues, dont confluent-kafka). Installe-le (winget install Python.Python.3.13) ou relance avec -InstallMissing."
    }
}
$pyArgs = @($py | Select-Object -Skip 1)
Ok ("Python : " + (& $py[0] @pyArgs --version))

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $venvVer = & $venvPython -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($PythonVersions -notcontains $venvVer) {
        Warn ".venv existant en Python $venvVer (non supporté) : il est recréé."
        Remove-Item -Recurse -Force (Join-Path $PSScriptRoot '.venv')
    }
}
if (-not (Test-Path $venvPython)) {
    Step 'Création de .venv'
    & $py[0] @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail 'Impossible de créer .venv.' }
}
Ok '.venv prêt'

Step 'Installation des dépendances (requirements.txt)'
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install a échoué (voir ci-dessus)." }
Ok 'dépendances installées'

# --- 2. Kafka (Docker) -------------------------------------------------------------------------
if (-not $SkipKafka) {
    Step 'Docker / Kafka'
    if (-not (Test-Command docker)) {
        if ($InstallMissing) { Install-WithWinget 'Docker.DockerDesktop' 'Docker Desktop' | Out-Null }
        if (-not (Test-Command docker)) {
            Warn 'Docker absent : Kafka ne sera pas utilisable (le mode rapide sans Kafka fonctionne quand même).'
            Warn 'Installe Docker Desktop (https://www.docker.com/products/docker-desktop/), redémarre, puis relance install.ps1.'
        }
    }
    if (Test-Command docker) {
        docker info *> $null
        if ($LASTEXITCODE -ne 0) {
            Warn "Docker est installé mais pas démarré : lance Docker Desktop puis relance install.ps1 pour télécharger l'image Kafka."
        } else {
            docker compose pull kafka
            if ($LASTEXITCODE -eq 0) { Ok 'image Kafka (apache/kafka:3.8.0) téléchargée' }
            else { Warn "Le téléchargement de l'image Kafka a échoué." }
            if ($Data) {
                docker compose --profile data pull postgres objects
                if ($LASTEXITCODE -eq 0) { Ok 'images PostgreSQL + pgvector et SeaweedFS (S3) téléchargées' }
                else { Warn "Le téléchargement des images de stockage a échoué." }
            }
        }
    }
}

# --- 3. Ollama ---------------------------------------------------------------------------------
if (-not $SkipOllama) {
    Step 'Ollama et modèles'
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama) {
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path $candidate) { $ollama = $candidate }
    }
    if (-not $ollama -and $InstallMissing) {
        Install-WithWinget 'Ollama.Ollama' 'Ollama' | Out-Null
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path $candidate) { $ollama = $candidate }
    }
    if (-not $ollama) {
        Warn 'Ollama absent : installe-le (https://ollama.com/download) ou relance avec -InstallMissing. Les pêcheurs utiliseront le faux LLM en attendant.'
    } else {
        Ok "Ollama : $ollama"
        $up = $false
        try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null; $up = $true } catch {}
        if (-not $up) {
            Write-Host '    Démarrage du serveur Ollama...'
            Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden
            for ($i = 0; $i -lt 30 -and -not $up; $i++) {
                Start-Sleep -Seconds 1
                try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null; $up = $true } catch {}
            }
        }
        if (-not $up) {
            Warn 'Le serveur Ollama ne répond pas sur localhost:11434 : lance l''application Ollama puis relance install.ps1.'
        } else {
            foreach ($m in $OllamaModels + $OptionalModels) {
                Write-Host "    ollama pull $m"
                & $ollama pull $m
                if ($LASTEXITCODE -eq 0) { Ok "modèle $m disponible" }
                elseif ($OptionalModels -contains $m) {
                    Warn "$m indisponible : il demande Ollama 0.40.4 ou plus (quitte Ollama, « winget upgrade Ollama.Ollama », relance)."
                }
                else { Warn "échec du téléchargement de $m" }
            }
        }
    }
}

# --- 4. Vérification ---------------------------------------------------------------------------
if (-not $SkipTests) {
    Step 'Vérification (pytest)'
    & $venvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail 'Des tests échouent : la simulation n''est pas prête.' }
    Ok 'simulation prête'
}

# --- 5. Godot ----------------------------------------------------------------------------------
Step 'Godot'
$pathFile = Join-Path $PSScriptRoot 'godot.path'
if ($GodotPath) {
    if (Test-Path $GodotPath) { Set-Content -Path $pathFile -Value $GodotPath -Encoding UTF8; Ok "chemin de Godot mémorisé dans godot.path" }
    else { Warn "Godot introuvable à l'emplacement donné : $GodotPath" }
}
$godot = $env:GODOT_PATH
if (-not $godot -and (Test-Path $pathFile)) { $godot = (Get-Content $pathFile -TotalCount 1).Trim() }
if (-not $godot) { $godot = (Get-Command godot*, Godot* -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
if ($godot -and (Test-Path $godot)) { Ok "Godot : $godot" }
else {
    Warn 'Godot non trouvé. Télécharge la version 4.3+ « Standard » (pas .NET) sur https://godotengine.org/download/,'
    Warn 'dézippe-la, puis donne son chemin à l''installation :'
    Warn '  .\install.ps1 -GodotPath "C:\Outils\Godot\Godot_v4.3-stable_win64.exe"'
    Warn 'Sinon, ouvre godot\project.godot à la main depuis Godot (Importer, puis F5).'
}

Write-Host "`nInstallation terminée. Lance le jeu avec :  .\start.ps1   (ou  .\start.ps1 -Kafka -Ollama)" -ForegroundColor Green
Write-Host "Godot s'ouvre sur un menu : tu y règles la partie (mode, saisons, pêcheurs), puis tu la lances." -ForegroundColor Green
