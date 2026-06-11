#!/usr/bin/env bash
# Transcribe every downloaded episode with the local faster-whisper setup.
# Japanese channel → force -l ja and large-v3 (per ~/repos/whisper/CLAUDE.md:
# auto-detect samples only the first ~30s and can mis-pick on a quiet intro).
#
# Idempotent: iterates files at the filesystem level (so Japanese/Unicode
# names match regardless of NFC/NFD normalization) and skips any episode whose
# .txt transcript already exists — safe to re-run / resume after interruption.
set -euo pipefail

WHISPER_DIR="${WHISPER_DIR:-$HOME/repos/whisper}"
PY="$WHISPER_DIR/venv/bin/python"
AUDIO_DIR="${1:-audio}"
OUT_DIR="${2:-transcripts}"
MODEL="${MODEL:-large-v3}"
LANG="${LANG_CODE:-ja}"

[ -x "$PY" ] || { echo "whisper venv python not found at $PY" >&2; exit 1; }
# AUDIO_DIR may be a directory or a single .m4a file (find handles both)
[ -e "$AUDIO_DIR" ] || { echo "audio path not found: $AUDIO_DIR" >&2; exit 1; }

mkdir -p "$OUT_DIR"
total=$(find "$AUDIO_DIR" -type f -name '*.m4a' | wc -l)
echo "Transcribing $total file(s): $AUDIO_DIR/ → $OUT_DIR/  (model=$MODEL lang=$LANG)"

i=0
done=0
find "$AUDIO_DIR" -type f -name '*.m4a' -print0 | sort -z | while IFS= read -r -d '' f; do
  i=$((i + 1))
  stem="$(basename "${f%.*}")"
  out="$OUT_DIR/$stem.txt"
  if [ -s "$out" ]; then
    echo "[$i/$total] ✓ skip (done): $stem"
    continue
  fi
  echo "[$i/$total] ↻ transcribing: $stem"
  "$PY" "$WHISPER_DIR/transcribe.py" "$f" -l "$LANG" -m "$MODEL" -o "$OUT_DIR"
  done=$((done + 1))
done

echo "Transcription pass complete."
