@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo  haystacked - Start
echo  ==================
echo.

:: Python pruefen
python --version > nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python wurde nicht gefunden.
    echo.
    echo  Bitte zuerst setup.bat ausfuehren, oder Python installieren:
    echo  https://www.python.org/downloads/
    echo  Wichtig: "Add Python to PATH" beim Setup ankreuzen!
    echo.
    pause
    exit /b 1
)

:: Ollama pruefen
ollama --version > nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Ollama wurde nicht gefunden.
    echo.
    echo  Bitte zuerst setup.bat ausfuehren, oder Ollama installieren:
    echo  https://ollama.com/download
    echo.
    pause
    exit /b 1
)

:: Ollama-Dienst starten falls noetig
ollama list > nul 2>&1
if errorlevel 1 (
    echo [..] Ollama wird gestartet...
    start "" /b ollama serve
    timeout /t 4 /nobreak > nul
)

:: Modell pruefen
ollama list 2>nul | findstr "qwen2.5" > nul
if errorlevel 1 (
    echo [FEHLER] Modell 'qwen2.5:7b' nicht gefunden.
    echo  Bitte setup.bat ausfuehren um das Modell herunterzuladen.
    echo.
    pause
    exit /b 1
)

:: Python-Pakete pruefen
python -c "import fastapi, uvicorn, pdfplumber" > nul 2>&1
if errorlevel 1 (
    echo [..] Fehlende Python-Pakete werden installiert...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [FEHLER] Paket-Installation fehlgeschlagen.
        pause
        exit /b 1
    )
)

:: Browser nach kurzem Delay oeffnen
start "" /b cmd /c "timeout /t 3 /nobreak > nul && start http://localhost:8000"

echo [OK] Alle Voraussetzungen erfuellt.
echo.
echo  App laeuft auf http://localhost:8000
echo  Dieses Fenster offen lassen - schliessen beendet die App.
echo.

:: Server starten
python -m uvicorn app:app --host 0.0.0.0 --port 8000
if errorlevel 1 (
    echo.
    echo [FEHLER] Server konnte nicht starten. Fehlermeldung siehe oben.
    pause
)
