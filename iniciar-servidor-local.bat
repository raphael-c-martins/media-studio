@echo off
chcp 65001 > nul
title Media Studio - Console
cd /d "%~dp0"

set PORTA=8810
set PYTHON=.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
if not exist "logs" mkdir "logs"

:menu
cls
echo.
echo  ==============================================
echo    MEDIA STUDIO  -  http://localhost:%PORTA%
echo  ==============================================
echo.
echo   [1] Ligar o servidor e abrir no navegador
echo   [2] Desligar o servidor
echo   [3] Ver situacao
echo   [4] Instalar / atualizar dependencias
echo   [5] Rodar os testes automatizados
echo   [0] Sair
echo.
set /p opcao="  Escolha: "

if "%opcao%"=="1" goto ligar
if "%opcao%"=="2" goto desligar
if "%opcao%"=="3" goto situacao
if "%opcao%"=="4" goto instalar
if "%opcao%"=="5" goto testes
if "%opcao%"=="0" exit /b
goto menu

:ligar
if not exist "%PYTHON%" (
    echo.
    echo  [!] Ambiente virtual nao encontrado. Rodando a instalacao primeiro...
    call :instalar_deps
)
netstat -ano | findstr /r /c:":%PORTA% .*LISTENING" > nul
if %errorlevel% equ 0 (
    echo.
    echo  [i] O servidor ja esta ligado. Abrindo o navegador...
    start "" http://localhost:%PORTA%
    timeout /t 2 /nobreak > nul
    goto menu
)
echo.
echo  [+] Ligando o servidor na porta %PORTA% (somente nesta maquina)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~dp0%PYTHON%' -ArgumentList '-m','app' -WorkingDirectory '%~dp0backend' -WindowStyle Hidden -RedirectStandardOutput '%~dp0logs\servidor-console.log' -RedirectStandardError '%~dp0logs\servidor-erros.log'"
for /l %%i in (1,1,20) do (
    timeout /t 1 /nobreak > nul
    netstat -ano | findstr /r /c:":%PORTA% .*LISTENING" > nul && goto ligado
)
echo  [!] O servidor nao respondeu. Veja logs\servidor-erros.log
pause
goto menu

:ligado
echo  [OK] Servidor no ar.
start "" http://localhost:%PORTA%
timeout /t 2 /nobreak > nul
goto menu

:desligar
echo.
set ACHOU=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%PORTA% .*LISTENING"') do (
    set ACHOU=1
    taskkill /PID %%p /F > nul 2>&1
    echo  [OK] Processo %%p encerrado.
)
if "%ACHOU%"=="0" echo  [i] O servidor ja estava desligado.
timeout /t 2 /nobreak > nul
goto menu

:situacao
echo.
netstat -ano | findstr /r /c:":%PORTA% .*LISTENING" > nul
if %errorlevel% equ 0 (
    echo  [OK] Ligado em http://localhost:%PORTA%
    powershell -NoProfile -Command "try { (Invoke-RestMethod http://127.0.0.1:%PORTA%/health) | Format-List } catch { Write-Host '  Sem resposta do /health' }"
) else (
    echo  [i] Desligado.
)
pause
goto menu

:instalar
call :instalar_deps
pause
goto menu

:instalar_deps
if not exist "%PYTHON%" (
    echo  [+] Criando ambiente virtual em .venv ...
    py -3.11 -m venv .venv 2> nul || python -m venv .venv
)
echo  [+] Instalando dependencias (backend\requirements.txt)...
"%PYTHON%" -m pip install --disable-pip-version-check -q -r backend\requirements-dev.txt
echo  [OK] Dependencias prontas.
exit /b 0

:testes
echo.
pushd backend
"..\%PYTHON%" -m pytest
popd
pause
goto menu
