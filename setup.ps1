#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function Ok   ($msg) { Write-Host "  OK  $msg" -ForegroundColor Green }
function Warn ($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }
function Err  ($msg) { Write-Host "  XX  $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "==> CamTrap Verify - setup" -ForegroundColor White
Write-Host ""

# -- Docker --------------------------------------------------------------------

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerVersion = (docker --version) -replace '^Docker version ([\d.]+).*', '$1'
    Ok "Docker $dockerVersion"
} else {
    Err "Docker no encontrado."
    Warn "Instalalo desde https://docs.docker.com/get-docker/ para poder usar el modo produccion."
}

# -- uv --------------------------------------------------------------------------

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Ok "uv $(uv --version)"
} else {
    Warn "uv no encontrado. Instalando..."
    Invoke-Expression (Invoke-RestMethod https://astral.sh/uv/install.ps1)

    $uvLocalBin = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path $uvLocalBin) {
        $env:Path = "$uvLocalBin;$env:Path"
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Ok "uv $(uv --version) instalado correctamente."
        Warn "Reinicia la terminal para que uv este disponible en nuevas sesiones."
    } else {
        Err "No se pudo instalar uv. Visita https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    }
}

# -- Backend - dependencias Python ----------------------------------------------

Write-Host ""
Write-Host "==> Instalando dependencias del backend..."
uv sync
if ($LASTEXITCODE -ne 0) {
    Err "uv sync fallo."
    exit 1
}
Ok "Dependencias del backend instaladas."

# -- Node.js / npm ----------------------------------------------------------------

Write-Host ""
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Err "Node.js no encontrado. Instalalo desde https://nodejs.org/ (v18+)"
    Warn "Saltando instalacion del frontend."
} else {
    $nodeVersion = node -e "process.stdout.write(process.versions.node)"
    $nodeMajor = [int]($nodeVersion -split '\.')[0]
    if ($nodeMajor -lt 18) {
        Err "Node.js $nodeVersion es demasiado antiguo. Se requiere v18+."
        Warn "Saltando instalacion del frontend."
    } else {
        Ok "Node.js $nodeVersion"

        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            Err "npm no encontrado. Debe venir incluido con Node.js."
        } else {
            Ok "npm $(npm --version)"
            Write-Host ""
            Write-Host "==> Instalando dependencias del frontend..."
            npm install --prefix frontend
            if ($LASTEXITCODE -ne 0) {
                Err "npm install fallo."
                exit 1
            }
            Ok "Dependencias del frontend instaladas."
        }
    }
}

# -- Resumen -----------------------------------------------------------------------

Write-Host ""
Write-Host "==> Listo. Para arrancar la aplicacion:"
Write-Host ""
Write-Host "    uv run cli dev                  <- backend + frontend (desarrollo)"
Write-Host "    uv run cli backend serve dev    <- solo backend"
Write-Host "    uv run cli frontend dev         <- solo frontend"
Write-Host ""
