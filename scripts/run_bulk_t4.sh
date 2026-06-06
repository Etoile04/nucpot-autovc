#!/bin/bash
set -e
cd /home/z203/nucpot-autovc
set -a && source .env && set +a

echo "=== T4: Slow-line bulk verification ==="
echo "Started at: $(date)"
echo ""

python3 scripts/bulk_verify.py --template basic --max-jobs 20 --delay 5

echo ""
echo "Finished at: $(date)"
echo "=== Done ==="
