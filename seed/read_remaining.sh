#!/bin/bash
# Read the pages of every book the heading pass could not fully group.
#
# One book at a time, in order of how much is missing, so an interruption
# costs the book in flight and nothing else. Every page read is cached in
# work/passages-book*-doc*.json, so re-running skips what is already read --
# which is what makes closing the laptop safe.
set -u
cd "$(dirname "$0")"

for BOOK in 103 101 16 10 12 13 14 17 102; do
  echo "=== book $BOOK  $(date +%H:%M:%S) ==="
  SEED_VISION=gemini .venv/bin/python locate_passages.py --book "$BOOK" --read || {
    echo "book $BOOK failed — its cache is kept, re-run to carry on"
  }
done

echo
echo "=== done  $(date +%H:%M:%S) ==="
.venv/bin/python locate_passages.py --report
