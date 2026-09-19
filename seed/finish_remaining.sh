#!/bin/bash
# Wait for the running batch, then read the two books it could not finish.
#
#   103  crashed on a test number the book does not have — the cap that
#        refuses those landed after it ran, so its cached pages regroup for
#        free.
#   14   lost one page to a 300s timeout, which is what a laptop asleep
#        mid-request looks like from the other end.
set -u
cd "$(dirname "$0")"

while pgrep -f "locate_passages.py" >/dev/null; do sleep 10; done

for BOOK in 103 14; do
  echo "=== book $BOOK  $(date +%H:%M:%S) ==="
  SEED_VISION=gemini .venv/bin/python -u locate_passages.py --book "$BOOK" --read \
    || echo "book $BOOK failed again — its cache is kept"
done

echo "=== done  $(date +%H:%M:%S) ==="
.venv/bin/python locate_passages.py --report
