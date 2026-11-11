#!/usr/bin/env bash
# Offline check of the Case B manifests: envsubst -> kubeconform (Flux + flux-operator schemas from the datree CRDs-catalog) -> flux-operator build resourceset.
# Needs: envsubst, kubeconform, flux-operator, yq. Never talks to a cluster.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./vars.example.env; set +a
export KUBECONFIG=/dev/null
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fo=https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json
for f in throwaway cluster-chart; do
  envsubst < $f.yaml > $tmp/$f.yaml
  # 1. the ResourceSet/RSIP objects themselves
  kubeconform -strict -summary -schema-location "$fo" $tmp/$f.yaml
  # 2. render the ResourceSet and check what it would apply
  yq 'select(.kind=="ResourceSet")' $tmp/$f.yaml > $tmp/rs.yaml
  flux-operator build resourceset -f $tmp/rs.yaml --inputs-from inputs.yaml > $tmp/out.yaml
  kubeconform -strict -summary -schema-location "$fo" $tmp/out.yaml
  # 3. assertions on the rendered HelmRelease
  hr='select(.kind=="HelmRelease")'
  [ "$(yq "$hr | .spec.releaseName" $tmp/out.yaml)" = "$RELEASE_NAME" ]
  [ "$(yq "$hr | .metadata.name" $tmp/out.yaml)" != "$RELEASE_NAME" ]
  [ "$(yq "$hr | .metadata.annotations.\"fluxcd.controlplane.io/prune\"" $tmp/out.yaml)" = disabled ]
  [ "$(yq 'select(.kind=="OCIRepository") | .spec.ref.tag' $tmp/out.yaml)" = "1.2.3" ]
  if [ $f = cluster-chart ]; then
    [ "$(yq "$hr | .spec.waitStrategy.name" $tmp/out.yaml)" = poller ]
    [ "$(yq "$hr | .spec.healthCheckExprs[0].kind" $tmp/out.yaml)" = Cluster ]
  fi
  echo "OK $f"
done
