#!/usr/bin/env bash
# helm template assertions for the customer ClusterRoles and the absence of a PolicyException.
set -euo pipefail
cd "$(dirname "$0")"
CHART=../../helm/crossplane-app-platform
out=$(helm template x "$CHART" -s templates/clusterrole-customer.yaml)
fail() { echo "FAIL $*"; exit 1; }
check() { [ "$(echo "$out" | yq ea "$1")" = "$2" ] || fail "$1 != $2"; }

check '[select(.kind=="ClusterRole")] | length' 3
for r in admin edit view; do
  role="select(.metadata.name==\"crossplane-app-platform-helmapp-$r\")"
  check "$role | .metadata.labels[\"rbac.authorization.k8s.io/aggregate-to-$r\"]" true
  check "$role | .rules | length" 1
  check "$role | .rules[0].apiGroups | join(\",\")" apps.giantswarm.io
  check "$role | .rules[0].resources | join(\",\")" helmapps,helmapps/status
done
check 'select(.metadata.name=="crossplane-app-platform-helmapp-view") | .rules[0].verbs | join(",")' get,list,watch
check 'select(.metadata.name=="crossplane-app-platform-helmapp-edit") | .rules[0].verbs | join(",")' '*'
# nothing cluster-wide beyond ClusterRoles, no Secret/ConfigMap access, no PolicyException
all=$(helm template x "$CHART")
echo "$all" | yq ea 'select(.kind=="ClusterRoleBinding" or .kind=="PolicyException")' | grep -q . && fail "unexpected binding or PolicyException"
echo "$out" | grep -q -E "secrets|configmaps" && fail "secret access in customer roles"
echo "PASS rbac"
