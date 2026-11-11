#!/usr/bin/env bash
# Golden tests: crossplane composition render on each fixture dir vs expected.yaml. UPDATE=1 rewrites expected.yaml.
# Optional per fixture: checks-off (chart default helmController.healthChecks=false), expect-error (render must fail with this text), observed.yaml (-o observed composed resources), required.yaml (-e extra resources).
set -euo pipefail
cd "$(dirname "$0")"
XP=${CROSSPLANE:-../../bin/crossplane}
CHART=../../helm/crossplane-app-platform
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
helm template x "$CHART" -s templates/composition.yaml --set helmController.healthChecks=true > "$tmp/composition.yaml"
# A fixture with a checks-off file renders with the chart default (healthChecks off).
helm template x "$CHART" -s templates/composition.yaml > "$tmp/composition-off.yaml"
rc=0
for d in */; do
  d=${d%/}
  extra=()
  comp="$tmp/composition.yaml"; [ -f "$d/checks-off" ] && comp="$tmp/composition-off.yaml"
  [ -f "$d/observed.yaml" ] && extra+=(-o "$d/observed.yaml")
  [ -f "$d/required.yaml" ] && extra+=(-e "$d/required.yaml")
  if [ -f "$d/expect-error" ]; then
    # The render must fail with the message in expect-error.
    if out=$("$XP" composition render "$d/xr.yaml" "$comp" functions.yaml "${extra[@]}" 2>&1); then echo "FAIL $d (render passed)"; rc=1
    elif grep -qF "$(cat "$d/expect-error")" <<<"$out"; then echo "PASS $d"; else echo "FAIL $d"; echo "$out"; rc=1; fi
    continue
  fi
  "$XP" composition render "$d/xr.yaml" "$comp" functions.yaml "${extra[@]}" > "$tmp/out.yaml"
  if [ "${UPDATE:-}" = 1 ]; then cp "$tmp/out.yaml" "$d/expected.yaml"; continue; fi
  if diff -u "$d/expected.yaml" "$tmp/out.yaml"; then echo "PASS $d"; else echo "FAIL $d"; rc=1; fi
done
exit $rc
