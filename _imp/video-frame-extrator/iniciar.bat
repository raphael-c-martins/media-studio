@echo off
title FrameStudio - Extrator de Frames de Alta Precisao
echo =======================================================
echo    FrameStudio - Extrator de Frames (Auto & Studio)
echo =======================================================
echo.
echo Iniciando a aplicacao no seu navegador padrao...
echo.

:: Verifica se o Python esta disponivel para subir o servidor com OpenCV
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Iniciando servidor FrameStudio com OpenCV (Porta 5522)...
    start "" http://localhost:5522
    python server.py
) else (
    echo [INFO] Abrindo diretamente no navegador padrao...
    start "" "%~dp0index.html"
)
