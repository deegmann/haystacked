#!/bin/bash
REQUIRED_MODEL="qwen2.5:7b"

# Ollama starten falls nötig
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "▶ Ollama wird gestartet..."
  ollama serve &> /tmp/ollama.log &
  sleep 2
fi

# Modell prüfen — schlägt fehl wenn nur das Manifest fehlt (Blob vorhanden)
if ! ollama show "$REQUIRED_MODEL" > /dev/null 2>&1; then
  echo "▶ $REQUIRED_MODEL nicht im Manifest — wird installiert..."
  ollama pull "$REQUIRED_MODEL" || { echo "✖ Pull fehlgeschlagen. Bitte manuell: ollama pull $REQUIRED_MODEL"; exit 1; }
fi
echo "✔ Modell $REQUIRED_MODEL verfügbar"

echo "▶ haystacked startet auf http://localhost:8000"
cd "$(dirname "$0")"
python3 -m uvicorn app:app --reload --reload-include "*.json" --host 0.0.0.0 --port 8000
