@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo ==========================================
echo    haystacked - Diagnose
echo ==========================================
echo.

:: Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [FEHLT]  Python  -^>  https://www.python.org/downloads/
    echo          Wichtig: "Add Python to PATH" ankreuzen!
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK]     %%v
)

:: Ollama
ollama --version > nul 2>&1
if errorlevel 1 (
    echo [FEHLT]  Ollama  -^>  https://ollama.com/download
) else (
    for /f "tokens=*" %%v in ('ollama --version 2^>^&1') do echo [OK]     Ollama %%v
)

:: Ollama laeuft?
ollama list > nul 2>&1
if errorlevel 1 (
    echo [WARN]   Ollama-Dienst laeuft nicht  -^>  setup.bat ausfuehren
) else (
    echo [OK]     Ollama-Dienst laeuft
)

:: Modell vorhanden?
ollama list 2>nul | findstr "qwen2.5" > nul
if errorlevel 1 (
    echo [FEHLT]  Modell qwen2.5:7b  -^>  setup.bat ausfuehren
) else (
    echo [OK]     Modell qwen2.5:7b vorhanden
)

:: Python-Pakete
python -c "import fastapi" > nul 2>&1
if errorlevel 1 (echo [FEHLT]  Python-Paket: fastapi) else (echo [OK]     fastapi)

python -c "import uvicorn" > nul 2>&1
if errorlevel 1 (echo [FEHLT]  Python-Paket: uvicorn) else (echo [OK]     uvicorn)

python -c "import pdfplumber" > nul 2>&1
if errorlevel 1 (echo [FEHLT]  Python-Paket: pdfplumber) else (echo [OK]     pdfplumber)

python -c "import httpx" > nul 2>&1
if errorlevel 1 (echo [FEHLT]  Python-Paket: httpx) else (echo [OK]     httpx)

:: Datenbankdatei
if exist "data\haystacked.db" (echo [OK]     data\haystacked.db) else (echo [FEHLT]  data\haystacked.db  -^>  sync_airtable.py ausfuehren)

echo.
echo Wenn alle Eintrage [OK] zeigen -^> start.bat ausfuehren.
echo Bei [FEHLT]-Eintragen -^> setup.bat ausfuehren.
echo.
pause
