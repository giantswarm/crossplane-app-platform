#!/usr/bin/env bash
# Golden tests: crossplane composition render on each fixture dir vs expected.yaml. UPDATE=1 rewrites expected.yaml.
set -euo pipefail
cd "$(dirname "$0")"
XP=${CROSSPLANE:-../../bin/crossplane}
CHART=../../helm/crossplane-app-platform
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
helm template x "$CHART" -s templates/composition.yaml > "$tmp/composition.yaml"
rc=0
for d in */; do
  d=${d%/}
  "$XP" composition render "$d/xr.yaml" "$tmp/composition.yaml" functions.yaml > "$tmp/out.yaml"
  if [ "${UPDATE:-}" = 1 ]; then cp "$tmp/out.yaml" "$d/expected.yaml"; continue; fi
  if diff -u "$d/expected.yaml" "$tmp/out.yaml"; then echo "PASS $d"; else echo "FAIL $d"; rc=1; fi
done
exit $rc
