@echo off
chcp 65001 > nul
title FrameStudio - Console de Operacoes
color 0B

cd /d "%~dp0"

:: Configuracao de Portas Dedicadas (Diferentes do padrao 5173 e 8000)
set PORTA_WEB=5522
set PORTA_API=8010

:: Garantir que a pasta de logs exista
if not exist "logs\logs-cmd" mkdir "logs\logs-cmd"

:: Captura de IP Local de forma compativel
set IP_LOCAL=
for /f "delims=" %%i in ('python -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()" 2^>nul') do set IP_LOCAL=%%i
if "%IP_LOCAL%"=="" (
    for /f %%i in ('powershell -NoProfile -Command "([System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) | Where-Object AddressFamily -eq 'InterNetwork' | Select-Object -ExpandProperty IPAddressToString -First 1)" 2^>nul') do set IP_LOCAL=%%i
)

:: Gerar data e hora sem dependencia de WMIC (Compativel com Windows 10 e 11)
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd')"') do set LOG_DATE=%%i
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('HH:mm:ss')"') do set LOG_TIME=%%i
set LOG_FILE=logs\logs-cmd\auditoria_%LOG_DATE%.log

echo. >> "%LOG_FILE%" 2>nul
echo ========================================== >> "%LOG_FILE%" 2>nul
echo FRAMESTUDIO - NOVA SESSAO AS %LOG_TIME% >> "%LOG_FILE%" 2>nul
echo ========================================== >> "%LOG_FILE%" 2>nul
echo. >> "%LOG_FILE%" 2>nul

:menu
cls
echo.
echo ======================================================
echo           FRAMESTUDIO - LAUNCHER LOCAL
echo ======================================================
echo.
echo [1] Ligar Servidor Web (Porta %PORTA_WEB%)
echo [2] Desligar Servidor
echo [3] Ver Status do Servidor
echo [4] Abrir Pasta do Projeto
echo [0] Sair
echo.
echo ======================================================
if not "%IP_LOCAL%"=="" echo IP Local da Maquina: %IP_LOCAL%
echo Porta Web Configurada: %PORTA_WEB%
echo ======================================================
set /p opcao="Escolha uma opcao: "

if "%opcao%"=="1" goto ligar
if "%opcao%"=="2" goto desligar
if "%opcao%"=="3" goto status
if "%opcao%"=="4" goto pasta
if "%opcao%"=="0" exit
goto menu

:ligar
echo.
set WEB_RUNNING=0

netstat -aon | findstr ":%PORTA_WEB% " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 set WEB_RUNNING=1

if "%WEB_RUNNING%"=="1" (
    echo [!] O Servidor Web ja esta rodando na porta %PORTA_WEB%!
    echo [!] Abrindo o navegador...
    timeout /t 2 /nobreak >nul 2>&1
    start http://localhost:%PORTA_WEB%
    goto menu
)

set WEB_LOG=logs\logs-cmd\servidor_background.log

echo [+] Iniciando Servidor Web na Porta %PORTA_WEB%...
echo [%time%] [+] Iniciando Servidor Web na porta %PORTA_WEB%... >> "%LOG_FILE%" 2>nul

:: Inicializacao em background via Python FastAPI + OpenCV Server
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Process cmd -ArgumentList '/c python server.py > %WEB_LOG% 2>&1' -WorkingDirectory '%~dp0' -WindowStyle Hidden"

echo.
echo [OK] Servidor inicializado com sucesso.
echo [!] Abrindo navegador...
timeout /t 2 /nobreak >nul 2>&1
start http://localhost:%PORTA_WEB%
goto menu

:desligar
echo.
echo [-] Encerrando processos do servidor...
echo [%time%] [-] Comando de encerramento enviado... >> "%LOG_FILE%" 2>nul

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORTA_WEB% " ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
    echo [%time%] [-] PID %%a - Servidor Web finalizado. >> "%LOG_FILE%" 2>nul
)

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORTA_API% " ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
    echo [%time%] [-] PID %%a - API finalizada. >> "%LOG_FILE%" 2>nul
)

echo [!] Servicos interrompidos.
timeout /t 2 /nobreak >nul 2>&1
goto menu

:status
echo.
echo [?] Verificando status do servidor...
echo [%time%] [?] Verificando status das portas... >> "%LOG_FILE%" 2>nul
echo.
echo --- SERVIDOR WEB (Porta %PORTA_WEB%) ---
netstat -aon | findstr ":%PORTA_WEB% " | findstr "LISTENING"
if %errorlevel% neq 0 (
    echo [OFFLINE] Servidor Web desligado.
    echo [%time%] [STATUS] Servidor Web OFFLINE. >> "%LOG_FILE%" 2>nul
) else (
    echo [ONLINE] Servidor Web operante em http://localhost:%PORTA_WEB%
    echo [%time%] [STATUS] Servidor Web ONLINE. >> "%LOG_FILE%" 2>nul
)

echo.
pause
goto menu

:pasta
start .
goto menu
