#!/bin/bash
set -e
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   haystacked – Setup                 ║"
echo "╚══════════════════════════════════════╝"
echo ""

# 1. Ollama installieren
if ! command -v ollama &> /dev/null; then
  echo "▶ Ollama wird installiert..."
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "✓ Ollama bereits installiert ($(ollama --version))"
fi

# 2. Ollama im Hintergrund starten (falls nicht läuft)
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "▶ Ollama wird gestartet..."
  ollama serve &> /tmp/ollama.log &
  sleep 3
else
  echo "✓ Ollama läuft bereits"
fi

# 3. LLM-Modell herunterladen
MODEL="qwen2.5:7b"
echo "▶ Modell '$MODEL' wird geladen (ca. 4.7 GB, einmalig)..."
ollama pull $MODEL
echo "✓ Modell bereit"

# 4. Python-Abhängigkeiten installieren
echo "▶ Python-Pakete werden installiert..."
pip3 install -r requirements.txt --quiet
echo "✓ Pakete installiert"

echo ""
echo "✅ Setup abgeschlossen! App starten mit:  ./start.sh"
echo ""
