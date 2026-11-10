# Migrate a HelmRelease to a HelmApp

This procedure moves one existing Flux `HelmRelease` under a `HelmApp` without a Helm uninstall.
The Helm release (its storage secrets and its workload) stays in place; only the object that delivers it changes.

Commands are marked **READ** (no change to the cluster) or **WRITE**. Do the READ checks; do not skip them.
All names below are placeholders: `<cluster>` is the workload cluster name, `<mc>` is the management cluster name,
`<ns>` is the namespace that holds the HelmRelease, `<app>` is the HelmApp name.

## 1. Pick the case

The HelmApp renders one HelmRelease per target, named `<cluster>-<app>` (for an `inCluster` target `<mc>-<app>`,
with `<mc>` read from the ConfigMap `flux-giantswarm/management-cluster-metadata`, key `NAME`), in the HelmApp namespace.

- **Case A, same name**: the old HelmRelease is in `<ns>` and is named `<cluster>-<app>`. The ResourceSet takes the
  object over in place.
- **Case B, different name**: any other name. The old HelmRelease is removed while it is suspended, and the new one
  adopts the Helm release by its `releaseName`.

Pick `<app>` so that Case A applies when you can: it has fewer steps. The HelmApp always goes in `<ns>`.

## 2. Map the old HelmRelease to the HelmApp

| Old HelmRelease | HelmApp |
|---|---|
| `metadata.namespace` | `metadata.namespace` (must be the same) |
| `spec.releaseName` | `spec.helmReleaseOverrides.releaseName` (default is `<app>`; set it when it differs) |
| `spec.serviceAccountName` | `spec.helmReleaseOverrides.serviceAccountName` (copy it as is; none stays none) |
| `spec.kubeConfig.secretRef.name` = `<cluster>-kubeconfig` | `spec.targets.static: [{cluster: <cluster>}]` |
| no `spec.kubeConfig` | `spec.targets.static: [{inCluster: true}]` |
| `spec.targetNamespace`, `spec.storageNamespace` (remote) | `spec.namespace` (both must be equal) |
| the chart name and source URL | `spec.chart.name`, `spec.chart.repository` (OCI only), `spec.chart.secretRef` for a private registry |
| the deployed chart version | `spec.chart.version`: pin the exact deployed version for the move, widen it later |
| `spec.values` | `spec.values` |
| `spec.valuesFrom` | `spec.valuesFrom`, minus the layers the HelmApp adds by itself (below) |
| `spec.dependsOn` | `spec.dependsOn.static`, or `spec.dependsOn.templated` with `%cluster%` |
| `spec.suspend` | `spec.suspend` |

Stop and do not migrate when one of these is true:

- A remote HelmRelease has `targetNamespace` different from `storageNamespace`. The HelmApp sets both to `spec.namespace`,
  and a different storage namespace does not find the release.
- An in-cluster HelmRelease has `targetNamespace` or `storageNamespace` different from `<ns>`. The HelmApp sets neither
  for an in-cluster target, so Helm uses `<ns>`.
- The chart is not in an OCI registry.

Possible differences after the move. Read them before you start:

- **valuesFrom layers.** For a remote target the HelmApp adds these optional entries by itself, in this order:
  `ConfigMap <cluster>-cluster-values` first, then `spec.valuesFrom`, then the target's `valuesFrom`, then
  `ConfigMap <cluster>-<app>-user-values` and `Secret <cluster>-<app>-user-values`. Do not repeat them in `spec.valuesFrom`.
  Flux merges `valuesFrom` in list order and `values` last, so a changed order can change the merged values.
  A HelmRelease made by the App CR converter sorts all ConfigMaps before all Secrets. An in-cluster target gets no
  added layers.
- **HelmRelease spec.** The HelmApp sets `interval: 5m`, install and upgrade `remediation.retries: 10`, upgrade
  `strategy: rollback`, `driftDetection.mode: warn` (default). It does not set `timeout` or `remediateLastFailure`.
  A converter-made HelmRelease has `timeout: 10m` and `remediateLastFailure`, so these fields change.
- **Protection.** Charts named `cluster-*` or `release-*` are protected by default (see [protection.md](protection.md)).
  Set `spec.protect: true` on every HelmApp during the move, so the rollback below can remove the HelmApp without
  an uninstall. You can remove it after the move.

## 3. Back up (READ)

```
kubectl --context <ctx> -n <ns> get helmrelease <old-hr> -o yaml > old-hr.yaml
helm --kube-context <ctx> -n <release-ns> history <release>
helm --kube-context <ctx> -n <release-ns> get values <release> -a > values.before.yaml
helm --kube-context <ctx> -n <release-ns> get manifest <release> > manifest.before.yaml
kubectl --context <ctx> -n <release-ns> get secret -l owner=helm,name=<release> -o name
```

`<ctx>` is the context of the cluster that holds the Helm release storage (the workload cluster for a remote target),
`<release-ns>` is its storage namespace. Write down the last revision number.

## 4. Render and compare (READ)

Write the HelmApp manifest. Render it offline with the function pipeline (see `tests/golden/run.sh` for the
`crossplane composition render` call) and compare the rendered HelmRelease with `old-hr.yaml`:

- `releaseName`, `serviceAccountName`, `targetNamespace`, `storageNamespace`, `kubeConfig` are the same.
- The merged values are the same as `values.before.yaml`, apart from changes you want.

## 5a. Case A: same name

1. **WRITE** (git) add `kustomize.toolkit.fluxcd.io/prune: disabled` to the old HelmRelease in its git source.
   Let the Kustomization apply it.
2. **READ** check the live object has the annotation:
   `kubectl --context <mc-ctx> -n <ns> get helmrelease <cluster>-<app> -o jsonpath='{.metadata.annotations}'`.
   If another tool than a Kustomization owns the object (for example an App CR and its operator), stop that tool from
   deleting the HelmRelease first, and write down what you changed.
3. **WRITE** (git) remove the old HelmRelease from git. The Kustomization does not prune it.
4. **READ** check the HelmRelease is still there and `Ready=True`.
5. **WRITE** (git) add the HelmApp.
6. **READ** check the takeover: the HelmApp is `Ready=True`, the HelmRelease has the ResourceSet labels, and
   `helm history` shows no uninstall and no fresh install (an upgrade revision is expected only if the spec or values
   changed). The ResourceSet takes field ownership from `kustomize-controller` (Flux Operator
   `internal/controller/common.go` `takeOwnershipFrom`), so fields the HelmApp does not set (for example an old
   `spec.chart`, `timeout`) are removed from the object.

## 5b. Case B: different name

1. **WRITE** (git) add `kustomize.toolkit.fluxcd.io/prune: disabled` and `spec.suspend: true` to the old HelmRelease in
   its git source. Let the Kustomization apply it. The same note about other owners as in Case A step 2 applies.
2. **READ** check both on the live object: `.spec.suspend` is `true` and the annotation is there.
3. **WRITE** delete the old HelmRelease while it is suspended:
   `kubectl --context <mc-ctx> -n <ns> delete helmrelease <old-hr>`.
   helm-controller uninstalls on delete only when the object is not suspended, so this leaves the release.
4. **WRITE** (git) remove the old HelmRelease from git.
5. **READ** check nothing was uninstalled: the Helm release secrets are still there, `helm history` has the same last
   revision, and the workload is untouched.
6. **WRITE** (git) add the HelmApp.
7. **READ** check the adoption: the new HelmRelease `<cluster>-<app>` runs one `upgrade` (log: `release not managed by
   controller: found existing release in storage`, then `running 'upgrade' action`), `helm history` shows a new
   revision with "Upgrade complete" and no uninstall, and the HelmApp is `Ready=True`.

## 5c. Cluster chart wrap

A cluster is delivered by a `cluster-<provider>` or `release-<provider>` chart on the management cluster. Wrap it with
Case A or Case B, with these settings:

- `spec.targets.static: [{inCluster: true}]`, and the HelmApp in the HelmRelease namespace (the organization namespace).
- `spec.chart.name` is the chart name, `spec.chart.version` is the deployed version.
- `spec.valuesFrom` is the old list, copied unchanged. `spec.values` is empty unless the old HelmRelease has values.
- Protection is on by default. Keep it on.
- The default CAPI `Cluster` health check needs helm-controller v1.5.0 or later and the chart value
  `helmController.healthChecks: true`. With the default (`false`) the HelmApp renders no health check.

Before the move, also back up the CAPI objects of the cluster (READ), and after the move check their UIDs and
`metadata.generation` did not change and no Machine was replaced.

## 6. Rollback

Before you remove the old HelmRelease backup, you can put the old delivery back:

1. **WRITE** (git) set `spec.suspend: true` on the HelmApp. **READ** check the new HelmRelease has `.spec.suspend` `true`.
2. **WRITE** (git) remove the HelmApp. With `spec.protect: true` the HelmRelease and the OCIRepository stay as orphans.
3. **WRITE** delete the orphaned HelmRelease while it is suspended (no uninstall), then the orphaned OCIRepository.
4. **WRITE** (git) put the old HelmRelease back from `old-hr.yaml` (without `status`, `resourceVersion`, `uid` and
   `suspend`). Its `releaseName` is the same, so it finds the release and runs one upgrade back.
5. If an upgrade left the release in a bad state, `upgrade.remediation.strategy: rollback` rolls it back. Otherwise run
   `helm rollback <release> <revision>` with the revision from step 3. The Helm release secrets from step 3 are the last resort.
