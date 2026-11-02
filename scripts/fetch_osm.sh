#!/usr/bin/env bash
# Download raw OpenStreetMap waterways and coastline into raw/ (git-ignored).
set -euo pipefail
endpoint="${OVERPASS_URL:-https://overpass.private.coffee/api/interpreter}"
bbox="29.45,34.2,33.45,35.95"
cd "$(dirname "$0")/.."
mkdir -p raw
curl -sSf -m 300 -A 'nachalim-build (github.com/komapc/nachalim)' "$endpoint" \
  --data-urlencode "data=[out:json][timeout:270];way[\"waterway\"~\"^(river|stream|canal|drain|wadi)$\"]($bbox);out tags geom;" \
  -o raw/ways.json
curl -sSf -m 150 -A 'nachalim-build (github.com/komapc/nachalim)' "$endpoint" \
  --data-urlencode "data=[out:json][timeout:110];way[\"natural\"=\"coastline\"]($bbox);out tags geom;" \
  -o raw/sinks.json
