#!/usr/bin/env bash
set -euo pipefail

FACTORIES_USED_CSV="./analytics/factories_used_2026-05-12.csv"
HANDLERS_CSV="./analytics/handlers.csv"
TO_SUPPORT_CSV="./analytics/to_support.csv"

awk -F, '
  NR == FNR {
    supported[$2] = 1
    next
  }
  FNR == 1 {
    print
    next
  }
  !($1 in supported) {
    print
  }
' "$HANDLERS_CSV" "$FACTORIES_USED_CSV" > "$TO_SUPPORT_CSV"

printf "Wrote %s\n" "$TO_SUPPORT_CSV"
