#!/usr/bin/env bash
# XRD validation tests, offline: pass/*.yaml must validate, fail/*.yaml must be rejected.
set -euo pipefail
cd "$(dirname "$0")"
XP=${CROSSPLANE:-../../bin/crossplane}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
helm template x ../../helm/crossplane-app-platform -s templates/xrd.yaml > "$tmp/xrd.yaml"
rc=0
for f in pass/*.yaml; do
  if out=$("$XP" resource validate "$tmp/xrd.yaml" "$f" 2>&1); then echo "PASS $f"; else echo "FAIL $f"; echo "$out"; rc=1; fi
done
for f in fail/*.yaml; do
  if "$XP" resource validate "$tmp/xrd.yaml" "$f" >/dev/null 2>&1; then echo "FAIL $f (accepted)"; rc=1; else echo "PASS $f"; fi
done
# The status the composition writes (golden xr.yaml spec + expected.yaml status): Crossplane applies it with a
# typed patch, so a field missing from the XRD status schema fails on the cluster.
for d in ../golden/*/; do
  [ -f "$d/expected.yaml" ] || continue
  st=$(yq 'select(.kind == "HelmApp") | .status' "$d/expected.yaml")
  yq ".status = $(echo "$st" | yq -o json -I0 .)" "$d/xr.yaml" > "$tmp/status.yaml"
  if out=$("$XP" resource validate "$tmp/xrd.yaml" "$tmp/status.yaml" 2>&1); then echo "PASS status $d"; else echo "FAIL status $d"; echo "$out"; rc=1; fi
done
# The API server cost estimator, which `resource validate` does not run.
(cd cost && go run . "$tmp/xrd.yaml") || rc=1
exit $rc
