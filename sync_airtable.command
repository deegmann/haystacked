#!/bin/bash
cd "$(dirname "$0")"
python3 sync_airtable.py
read -p "Druecke Enter zum Schliessen..."
