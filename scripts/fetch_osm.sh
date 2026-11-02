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
# Waterways around the box, to continue streams that cross its edge.
mkdir -p raw/outside
fetch_strip() {
  curl -sSf -m 280 -A 'nachalim-build (github.com/komapc/nachalim)' "$endpoint" \
    --data-urlencode "data=[out:json][timeout:270];way[\"waterway\"~\"^(river|stream|canal|wadi)$\"]($2);out tags geom;" \
    -o "raw/outside/$1.json"
}
fetch_strip north 33.45,35.0,34.15,36.45
fetch_strip east 29.3,35.95,33.45,36.8
fetch_strip west 29.9,32.9,31.45,34.2
fetch_strip south 28.9,34.2,29.45,35.95
