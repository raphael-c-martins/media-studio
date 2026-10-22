# Script de Inicialização de Servidores Desvinculados (Background) - MediaDownloader Pro
$ErrorActionPreference = "SilentlyContinue"

$rootDir = Split-Path -Parent $PSScriptRoot
Set-Location $rootDir

$venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"
$backendDir = Join-Path $rootDir "backend"
$frontendDir = Join-Path $rootDir "frontend"
$logsDir = Join-Path $rootDir "logs\logs-cmd"

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

# 1. Verificar Dependências
if (-not (Test-Path $venvPython)) {
    Write-Host "[!] Ambiente virtual nao encontrado. Executando instalador inicial..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "install-deps.ps1")
}

# 2. Iniciar Backend (FastAPI na porta 8800) de forma desvinculada e oculta
$beListening = Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue
if (-not $beListening) {
    Write-Host "[+] Iniciando Backend (FastAPI :8800 em segundo plano)..." -ForegroundColor Cyan
    $env:PYTHONPATH = $backendDir
    Start-Process -FilePath $venvPython -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 8800" -WorkingDirectory $backendDir -WindowStyle Hidden
} else {
    Write-Host "[*] Backend ja esta ativo na porta 8800." -ForegroundColor Yellow
}

# 3. Iniciar Frontend (Vite na porta 3030) de forma desvinculada e oculta
$feListening = Get-NetTCPConnection -LocalPort 3030 -State Listen -ErrorAction SilentlyContinue
if (-not $feListening) {
    Write-Host "[+] Iniciando Frontend (Vite :3030 em segundo plano)..." -ForegroundColor Cyan
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory $frontendDir -WindowStyle Hidden
} else {
    Write-Host "[*] Frontend ja esta ativo na porta 3030." -ForegroundColor Yellow
}

# 4. Aguardar prontidão dos sockets TCP
Write-Host "[*] Aguardando servidores ficarem online..." -ForegroundColor Gray
$ready = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    $beCheck = Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue
    $feCheck = Get-NetTCPConnection -LocalPort 3030 -State Listen -ErrorAction SilentlyContinue
    if ($beCheck -and $feCheck) {
        $ready = $true
        break
    }
}

if ($ready) {
    Write-Host "`n[OK] Backend e Frontend operantes em segundo plano!" -ForegroundColor Green
    Write-Host " -> Backend:  http://localhost:8800" -ForegroundColor Gray
    Write-Host " -> Frontend: http://localhost:3030" -ForegroundColor Gray
} else {
    Write-Host "`n[!] Os servidores estao iniciando em segundo plano." -ForegroundColor Yellow
}

Write-Host "`n[*] Abrindo navegador em http://localhost:3030..." -ForegroundColor Cyan
Start-Process "http://localhost:3030"
