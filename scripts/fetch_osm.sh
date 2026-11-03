#!/usr/bin/env bash
# Download raw OpenStreetMap waterways and coastline into raw/ (git-ignored).
# Set OVERPASS_URL to use another Overpass server. Boxes are south,west,north,east.
set -euo pipefail
endpoint="${OVERPASS_URL:-https://overpass.private.coffee/api/interpreter}"
bbox="29.45,34.2,33.45,35.95"  # BOX in build_outside.py
cd "$(dirname "$0")/.."
mkdir -p raw/outside

# overpass OUT_FILE CURL_TIMEOUT QUERY_TIMEOUT SELECTOR
overpass() {
  curl -sSf -m "$2" -A 'nachalim-build (github.com/komapc/nachalim)' "$endpoint" \
    --data-urlencode "data=[out:json][timeout:$3];$4;out tags geom;" \
    -o "$1"
}

overpass raw/ways.json 300 270 "way[\"waterway\"~\"^(river|stream|canal|drain|wadi)$\"]($bbox)"
overpass raw/sinks.json 150 110 "way[\"natural\"=\"coastline\"]($bbox)"

# Waterways around the box, to continue streams that cross its edge.
fetch_strip() {
  overpass "raw/outside/$1.json" 280 270 "way[\"waterway\"~\"^(river|stream|canal|wadi)$\"]($2)"
}
fetch_strip north 33.45,35.0,34.15,36.45
fetch_strip east 29.3,35.95,33.45,36.8
fetch_strip west 29.9,32.9,31.45,34.2
fetch_strip south 28.9,34.2,29.45,35.95
