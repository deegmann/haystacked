#!/bin/bash
# Ollama im Hintergrund starten falls nötig
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "▶ Ollama wird gestartet..."
  ollama serve &> /tmp/ollama.log &
  sleep 2
fi

echo "▶ haystacked startet auf http://localhost:8000"
cd "$(dirname "$0")"
python3 -m uvicorn app:app --reload --reload-include "*.json" --host 0.0.0.0 --port 8000
