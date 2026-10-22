# Script de Diagnóstico de Status dos Servidores
$feConn = Get-NetTCPConnection -LocalPort 3030 -State Listen -ErrorAction SilentlyContinue
$beConn = Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue

Write-Host "`n======================================================" -ForegroundColor Cyan
Write-Host "              STATUS DOS SERVIDORES" -ForegroundColor Cyan
Write-Host "======================================================`n" -ForegroundColor Cyan

if ($feConn) {
    Write-Host " [ONLINE]  Frontend na porta 3030 (PID: $($feConn.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host " [OFFLINE] Frontend na porta 3030" -ForegroundColor Red
}

if ($beConn) {
    Write-Host " [ONLINE]  Backend na porta 8800 (PID: $($beConn.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host " [OFFLINE] Backend na porta 8800" -ForegroundColor Red
}

# Verificação de saúde HTTP
if ($beConn) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8800/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($health) {
            Write-Host "`nDiagnostico da API:" -ForegroundColor Gray
            Write-Host " -> Versao yt-dlp: $($health.yt_dlp_version)" -ForegroundColor Gray
            Write-Host " -> Espaco Livre:  $($health.storage.free_space_gb) GB" -ForegroundColor Gray
            Write-Host " -> SQLite:        $($health.database_connected)" -ForegroundColor Gray
        }
    } catch {}
}
Write-Host ""
