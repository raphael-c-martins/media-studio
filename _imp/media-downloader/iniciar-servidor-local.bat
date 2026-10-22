@echo off
chcp 65001 > nul
title MediaDownloader Pro - Console de Operacoes
color 0B

cd /d "%~dp0"

:menu
cls
echo ======================================================
echo           MEDIADOWNLOADER PRO - LAUNCHER
echo ======================================================
echo.
echo  [1] Ligar Sistema (Frontend :3030 + Backend :8800)
echo  [2] Desligar Sistema
echo  [3] Ver Status dos Servidores
echo  [4] Instalar / Atualizar Dependencias
echo  [5] Abrir Pasta de Downloads
echo  [6] Abrir Pasta do Projeto
echo  [0] Sair
echo.
echo ======================================================
echo  Acesso Web: http://localhost:3030
echo ======================================================
set /p opcao="Escolha uma opcao: "

if "%opcao%"=="1" goto ligar
if "%opcao%"=="2" goto desligar
if "%opcao%"=="3" goto status
if "%opcao%"=="4" goto instalar_deps
if "%opcao%"=="5" goto pasta_downloads
if "%opcao%"=="6" goto pasta_projeto
if "%opcao%"=="0" exit
goto menu

:ligar
cls
echo.
echo ======================================================
echo           INICIANDO MEDIADOWNLOADER PRO
echo ======================================================
echo.
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\start-all.ps1"
echo.
echo Pressione qualquer tecla para voltar ao menu...
pause > nul
goto menu

:desligar
cls
echo.
echo ======================================================
echo           ENCERRANDO MEDIADOWNLOADER PRO
echo ======================================================
echo.
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\stop-all.ps1"
echo.
timeout /t 2 > nul
goto menu

:status
cls
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\status-all.ps1"
echo.
echo Pressione qualquer tecla para voltar ao menu...
pause > nul
goto menu

:instalar_deps
cls
echo.
echo ======================================================
echo           INSTALANDO DEPENDENCIAS
echo ======================================================
echo.
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\install-deps.ps1"
echo.
echo Pressione qualquer tecla para voltar ao menu...
pause > nul
goto menu

:pasta_downloads
if not exist "%~dp0downloads" mkdir "%~dp0downloads"
start "" "%~dp0downloads"
goto menu

:pasta_projeto
start "" "%~dp0"
goto menu
