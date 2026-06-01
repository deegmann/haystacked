@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo ==========================================
echo    haystacked - Setup (Windows)
echo ==========================================
echo.

:: 1. Python pruefen
python --version > nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python nicht gefunden.
    echo Bitte Python 3.11+ von https://www.python.org/downloads/ installieren.
    echo Wichtig: "Add Python to PATH" beim Setup ankreuzen!
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% gefunden

:: 2. Ollama pruefen
ollama --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo [FEHLER] Ollama nicht gefunden.
    echo Bitte Ollama von https://ollama.com/download installieren und
    echo danach dieses Setup erneut starten.
    echo.
    pause
    exit /b 1
)
echo [OK] Ollama gefunden

:: 3. Ollama-Dienst starten
curl -s http://localhost:11434/api/tags > nul 2>&1
if errorlevel 1 (
    echo [..] Ollama wird gestartet...
    start /b ollama serve > nul 2>&1
    timeout /t 4 /nobreak > nul
) else (
    echo [OK] Ollama laeuft bereits
)

:: 4. LLM-Modell herunterladen
echo [..] Modell 'qwen2.5:7b' wird geprueft/geladen (ca. 4.7 GB, einmalig)...
ollama pull qwen2.5:7b
if errorlevel 1 (
    echo [FEHLER] Modell konnte nicht geladen werden.
    pause
    exit /b 1
)
echo [OK] Modell bereit

:: 5. Python-Pakete installieren
echo [..] Python-Pakete werden installiert...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [FEHLER] Paket-Installation fehlgeschlagen.
    pause
    exit /b 1
)
echo [OK] Pakete installiert

echo.
echo ==========================================
echo  Setup abgeschlossen!
echo  App starten mit:  start.bat
echo ==========================================
echo.
pause
