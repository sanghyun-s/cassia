#!/bin/bash
# =============================================================
# backup_app2.sh — dated CoReckoner backup
# =============================================================
# Usage:
#   ./backup_app2.sh            → tag "misc"
#   ./backup_app2.sh phase4b1   → tag "phase4b1"
#
# Produces:  ~/Desktop/application backup zips/app2_backup_<date>_<tag>.zip
#
# Excludes the big regeneratable stuff (venv, ChromaDB, per-session SQLite,
# __pycache__, .git) so the zip stays small and meaningful. The code,
# coreckoner.db, accounting.db, and data/ are all included.
# =============================================================

set -euo pipefail

PHASE="${1:-misc}"
SRC="/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot"
DEST="$HOME/Desktop/application backup zips"
TIMESTAMP=$(date +%Y-%m-%d_%H%M)
ZIPNAME="app2_backup_${TIMESTAMP}_${PHASE}.zip"

mkdir -p "$DEST"
cd "$SRC"

zip -r "$DEST/$ZIPNAME" app2 \
  -x "app2/venv/*" \
     "app2/outputs/chroma_db/*" \
     "app2/outputs/sessions/*" \
     "app2/__pycache__/*" \
     "app2/**/__pycache__/*" \
     "app2/**/.DS_Store" \
     "app2/.DS_Store" \
     "app2/.git/*" \
  > /dev/null

SIZE=$(du -h "$DEST/$ZIPNAME" | cut -f1)
echo "✓ Backed up: $ZIPNAME ($SIZE)"
echo "  → $DEST/"
