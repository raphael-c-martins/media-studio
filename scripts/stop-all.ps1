# Script de Encerramento dos Servidores
$ErrorActionPreference = "SilentlyContinue"

$ports = @(3030, 8800)
$terminated = 0

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connections) {
        foreach ($conn in $connections) {
            $p = $conn.OwningProcess
            if ($p -and $p -ne 0) {
                Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
                Write-Host "[-] Processo PID $p finalizado (Porta $port)." -ForegroundColor Yellow
                $terminated++
            }
        }
    }
}

if ($terminated -gt 0) {
    Write-Host "`n[OK] Todos os servicos foram encerrados com sucesso." -ForegroundColor Green
} else {
    Write-Host "`n[*] Nenhum servico estava ativo nas portas 3030 e 8800." -ForegroundColor Gray
}
