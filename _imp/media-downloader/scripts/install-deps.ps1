# Script de Instalação e Atualização de Dependências
$ErrorActionPreference = "Continue"

$rootDir = Split-Path -Parent $PSScriptRoot
Set-Location $rootDir

Write-Host "`n[*] Verificando ambiente virtual Python (.venv)..." -ForegroundColor Cyan
$venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[+] Criando ambiente virtual em .venv..." -ForegroundColor Yellow
    python -m venv (Join-Path $rootDir ".venv")
}

Write-Host "[+] Atualizando pip..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip

Write-Host "[+] Instalando dependencias do backend (requirements.txt)..." -ForegroundColor Cyan
$reqFile = Join-Path $rootDir "backend\requirements.txt"
& $venvPython -m pip install -r $reqFile

Write-Host "`n[*] Verificando dependencias do Frontend (npm install)..." -ForegroundColor Cyan
$frontendDir = Join-Path $rootDir "frontend"
Set-Location $frontendDir
npm install
Set-Location $rootDir

Write-Host "`n[OK] Todas as dependencias foram instaladas e verificadas com sucesso!" -ForegroundColor Green
