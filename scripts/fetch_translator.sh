#!/bin/bash
# Download Helsinki-NLP/opus-mt-zh-en and convert it to a CTranslate2 int8
# model. PyInstaller bundles the result so users get offline ZH->EN
# translation with no extra deps at runtime (ctranslate2 already ships via
# faster-whisper; we only add sentencepiece).
#
# Runs in a throw-away venv because the converter needs torch + transformers
# but the runtime does NOT. Keeps the .app bundle small.

set -eo pipefail
cd "$(dirname "$0")/.."

OUT="models/opus-mt-zh-en"
if [ -f "$OUT/model.bin" ] && [ -f "$OUT/source.spm" ] && [ -f "$OUT/target.spm" ]; then
  echo "Translator already converted at $OUT, skipping."
  ls -lh "$OUT" 2>/dev/null || true
  exit 0
fi

mkdir -p models
TMP=$(mktemp -d)
trap "rm -rf '$TMP'" EXIT

PY="${PYTHON:-python3}"
echo "Creating temp venv for Marian -> CTranslate2 conversion..."
"$PY" -m venv "$TMP/venv"
VPY="$TMP/venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip

# torch is the heaviest dep here (~200 MB) but it's build-time only -- we
# DO NOT bundle it. ct2-transformers-converter needs it to load the
# Helsinki-NLP weights before re-serialising to CT2 format.
echo "Installing converter deps into temp venv (one-time, ~600 MB download)..."
"$VPY" -m pip install --quiet \
  "ctranslate2>=4.0,<5" \
  "transformers>=4.36,<5" \
  "torch>=2.0,<3" \
  "sentencepiece>=0.1.99"

echo "Running ct2-transformers-converter (Helsinki-NLP/opus-mt-zh-en, int8)..."
"$TMP/venv/bin/ct2-transformers-converter" \
  --model Helsinki-NLP/opus-mt-zh-en \
  --output_dir "$OUT" \
  --quantization int8 \
  --copy_files source.spm target.spm tokenizer_config.json vocab.json \
  --force

if [ ! -f "$OUT/model.bin" ]; then
  echo "ERROR: conversion failed -- model.bin not produced"
  exit 1
fi

echo ""
echo "Converted opus-mt-zh-en CT2 model:"
ls -lh "$OUT"
echo ""
echo "Total size:"
du -sh "$OUT"
