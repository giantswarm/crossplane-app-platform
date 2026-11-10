#!/usr/bin/env bash
# The zero-window CEL rule is not exercised by `crossplane render` (it does not validate against the XRD),
# so this only checks the rule text is in the rendered XRD. A live API server rejection is untested.
set -euo pipefail
cd "$(dirname "$0")"
xrd=$(helm template x ../../helm/crossplane-app-platform -s templates/xrd.yaml)
rule=$(echo "$xrd" | yq '.spec.versions[0].schema.openAPIV3Schema.properties.spec.properties.schedule.properties.windows.items["x-kubernetes-validations"][0].rule')
[ "$rule" = "duration(self.window) >= duration('4m')" ] || { echo "FAIL window rule: $rule"; exit 1; }
req=$(echo "$xrd" | yq '.spec.versions[0].schema.openAPIV3Schema.properties.spec.properties.schedule.properties.windows.items.required | join(",")')
[ "$req" = "cron,window" ] || { echo "FAIL required: $req"; exit 1; }
echo "PASS schedule window rule text"
