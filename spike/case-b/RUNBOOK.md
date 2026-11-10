# Case B spike runbook: adopt a Helm release under a different-name HelmRelease

Ticket: https://github.com/giantswarm/crossplane-app-platform/issues/2
Spec: the adoption, protection and health-check sections of the HelmApp PRD (honeybadger-plans, `app-manifest/PRD.md`).

A human runs this by hand. Nothing in this repo touches a cluster. Commands marked
**READ** are read-only; commands marked **WRITE** change the cluster.
Use a test management cluster only. Placeholders (`<...>`) are never real names in this public repo;
keep real values in `vars.env` (gitignored).

## Files

| File | What |
|---|---|
| `throwaway.yaml` | RSIP + ResourceSet for a throwaway release (no health check) |
| `cluster-chart.yaml` | same, plus the CAPI `Cluster` Ready CEL check with the `poller` wait strategy |
| `vars.example.env` | the variables both files use |
| `inputs.yaml`, `validate.sh` | offline validation, no cluster (`make -C ../.. validate-spike-case-b`, or run `./validate.sh`) |

## Preconditions (check first, all READ)

1. helm-controller >= v1.5.0. It brings `spec.healthCheckExprs` (CEL) and `spec.waitStrategy`
   (helm-controller `CHANGELOG.md`, "1.5.0", "custom health checks via CEL"; fields at
   `api/v2/helmrelease_types.go:198-209`). CEL runs only when wait is on (`disableWait` unset) and the strategy is `poller`.
   ```
   kubectl -n flux-system get deploy helm-controller -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   ```
2. flux-operator that honours `fluxcd.controlplane.io/prune: disabled`. Verified in flux-operator v0.59.0
   (clone `fo059`, commit e0f71db): the annotation constant is `api/v1/common_types.go:32`; the ResourceSet
   garbage collection excludes objects carrying it (`internal/controller/resourceset_controller.go:665-670`), and so does
   the delete/uninstall path of the ResourceSet (`resourceset_controller.go:967-972`). The exclusion is checked on the
   live object (`ssa.DeleteOptions.Exclusions`). Older versions were not checked: use >= v0.59.0.
   ```
   kubectl -n flux-system get deploy flux-operator -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   kubectl get crd resourcesets.fluxcd.controlplane.io resourcesetinputproviders.fluxcd.controlplane.io
   ```
3. The HelmRelease namespace equals the Helm storage namespace of the existing release (the manifests set no `storageNamespace`
   and no `targetNamespace`). If the existing release uses others, add the same values to the new HelmRelease.
4. Same chart, same version (or the next one), same values as the old HelmRelease. The new HelmRelease must carry
   the same `valuesFrom` entries (same order and `valuesKey`) as the old one, and no inline `values` unless the old one had them. Otherwise
   the adoption upgrade changes the release.
5. Run `./validate.sh` once. It must print `OK throwaway` and `OK cluster-chart`.

## Set up variables

```
cp vars.example.env vars.env     # edit: NAMESPACE, NEW_HR_NAME, RELEASE_NAME, CHART_URL, CHART_VERSION
set -a; . ./vars.env; set +a
envsubst < throwaway.yaml > /tmp/case-b-throwaway.yaml     # or cluster-chart.yaml
```

`RELEASE_NAME` is the existing Helm release name. `NEW_HR_NAME` must differ from the old HelmRelease name
(that is Case B). `CHART_VERSION` is the exact tag the new HelmRelease installs.

## Old delivery object: how it goes away without an uninstall

helm-controller uninstalls on HelmRelease delete only when the object is not suspended
(helm-controller `internal/controller/helmrelease_controller.go:470-476`, finalizer removed at `:482`). So:

1. **READ** back up first:
   ```
   kubectl -n $NAMESPACE get helmrelease <OLD_HR_NAME> -o yaml > old-hr.yaml
   helm -n $NAMESPACE history $RELEASE_NAME
   helm -n $NAMESPACE get values $RELEASE_NAME -a > release-values.before.yaml
   helm -n $NAMESPACE get manifest $RELEASE_NAME > release-manifest.before.yaml
   kubectl -n $NAMESPACE get secret -l owner=helm,name=$RELEASE_NAME -o name
   ```
2. If a Kustomization or GitOps source owns the old HelmRelease, first add
   `kustomize.toolkit.fluxcd.io/prune: disabled` to it there (otherwise removing it from git prunes it, with an uninstall),
   and **READ** that the live object has it. If another tool owns it (App CR, app-operator, converter), stop that tool
   from deleting the HelmRelease on its own, and write down what it was.
3. **WRITE** suspend the old HelmRelease:
   ```
   kubectl -n $NAMESPACE patch helmrelease <OLD_HR_NAME> --type merge -p '{"spec":{"suspend":true}}'
   ```
   **READ** helm-controller sees it: `kubectl -n $NAMESPACE get helmrelease <OLD_HR_NAME> -o jsonpath='{.spec.suspend}{"\n"}'`
   gives `true`, and `kubectl -n flux-system logs deploy/helm-controller --tail=50 | grep -i suspended` shows a line for it.
4. **WRITE** delete it while suspended: `kubectl -n $NAMESPACE delete helmrelease <OLD_HR_NAME>`.
5. **READ** nothing was uninstalled: the Helm release and its secrets are still there and the workload is untouched
   (see Check 1 for the commands).

## Check 1: adopt without an uninstall (throwaway release first)

Do this with a throwaway release (any small public chart installed by a plain HelmRelease), then
repeat with the test cluster chart (Check 2).

1. **READ** before:
   ```
   helm -n $NAMESPACE list -a --filter "^$RELEASE_NAME$"
   helm -n $NAMESPACE history $RELEASE_NAME           # note the last revision, call it vN
   kubectl -n $NAMESPACE get pods -o wide > pods.before.txt
   ```
2. Remove the old object (section above), then **WRITE** `kubectl apply -f /tmp/case-b-throwaway.yaml`.
3. **READ** the new objects get ready and the RSIP exported the tag:
   ```
   kubectl -n $NAMESPACE get resourcesetinputprovider,resourceset,ocirepository,helmrelease
   kubectl -n $NAMESPACE get resourcesetinputprovider $NEW_HR_NAME -o jsonpath='{.status.exportedInputs}{"\n"}'
   kubectl -n $NAMESPACE describe helmrelease $NEW_HR_NAME
   ```
4. **READ** proof of adoption. Expected: the history has exactly one new revision `vN+1`, status `deployed`, and no revision
   `v1` with a fresh install after an `uninstalled` one; the pods keep their names and ages unless the chart changed them.
   ```
   helm -n $NAMESPACE history $RELEASE_NAME           # expect ... vN, then vN+1 "Upgrade complete"; no "Uninstallation complete"
   kubectl -n $NAMESPACE get secret -l owner=helm,name=$RELEASE_NAME --sort-by=.metadata.creationTimestamp
   kubectl -n flux-system logs deploy/helm-controller --tail=200 | grep $NEW_HR_NAME
   kubectl -n $NAMESPACE get helmrelease $NEW_HR_NAME -o jsonpath='{.status.history[0]}{"\n"}'
   diff pods.before.txt <(kubectl -n $NAMESPACE get pods -o wide)
   ```
   The controller log must say `release not managed by controller: found existing release in storage` and then an upgrade, and no install
   (code path: helm-controller `internal/reconcile/state.go:126-130`, `internal/reconcile/atomic_release.go:436-443`; a new HelmRelease has an empty `status.history`, so the
   release is "Unmanaged" and gets one `helm upgrade`).
5. Pass if: `.vN` -> `.vN+1`, no uninstall event, no fresh install.

## Check 2: test cluster chart, CAPI objects untouched

Use `cluster-chart.yaml` and a **test** cluster. Same flow as Check 1, plus:

1. **READ** before and after, and compare. `uid` and `generation` must be equal; `resourceVersion` may move because CAPI writes status:
   ```
   kubectl -n $NAMESPACE get clusters.cluster.x-k8s.io $CLUSTER_NAME -o jsonpath='{.metadata.uid} {.metadata.generation}{"\n"}'
   kubectl -n $NAMESPACE get clusters.cluster.x-k8s.io,machinedeployments,machinepools,kubeadmcontrolplanes -o custom-columns=KIND:.kind,NAME:.metadata.name,UID:.metadata.uid,GEN:.metadata.generation
   kubectl -n $NAMESPACE get machines.cluster.x-k8s.io -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,PHASE:.status.phase
   ```
   Pass if no UID changed, no Machine was created or deleted, no generation moved, and the cluster stays `Ready`.
   (Also add provider-specific objects of your cluster chart to the list.)
2. The old HelmRelease of a cluster chart often has a different chart name or version (the PRD uses `release-<provider>`). For the spike,
   keep the same chart and version, so the upgrade has no diff. Diff the manifests:
   `diff release-manifest.before.yaml <(helm -n $NAMESPACE get manifest $RELEASE_NAME)` should be empty or only annotation noise.
3. If you can, run the upgrade first as a dry run: `helm -n $NAMESPACE upgrade $RELEASE_NAME <chart> --version $CHART_VERSION --reuse-values --dry-run=server`
   (needs registry access, no cluster change).

## Check 3: deleting the ResourceSet leaves the release

1. **READ** the guard is on the live object: `kubectl -n $NAMESPACE get helmrelease $NEW_HR_NAME -o jsonpath='{.metadata.annotations}{"\n"}'` shows `fluxcd.controlplane.io/prune":"disabled"`.
2. **WRITE** `kubectl -n $NAMESPACE delete resourceset $NEW_HR_NAME` (wait for it to finish; it has a finalizer).
3. **READ**:
   ```
   kubectl -n $NAMESPACE get helmrelease $NEW_HR_NAME                  # still there
   kubectl -n $NAMESPACE get ocirepository $NEW_HR_NAME                # expected: gone (not guarded in the PRD render)
   helm -n $NAMESPACE list -a --filter "^$RELEASE_NAME$"               # still deployed
   helm -n $NAMESPACE history $RELEASE_NAME                            # no new revision, no uninstall
   kubectl -n $NAMESPACE get pods -o wide                              # unchanged
   ```
   Pass if the HelmRelease object and the Helm release survive. Record what the orphaned HelmRelease reports once its OCIRepository is gone
   (expected `SourceNotReady` or similar, release untouched). The PRD guards only the HelmRelease: write down whether the unguarded
   OCIRepository is a problem for the migration.
4. To restore: `kubectl apply -f /tmp/case-b-*.yaml` again; **READ** that the ResourceSet takes the orphaned HelmRelease back.

## Check 4: CEL check reports Ready (cluster chart)

1. **READ** the rendered check: `kubectl -n $NAMESPACE get helmrelease $NEW_HR_NAME -o jsonpath='{.spec.waitStrategy}{"\n"}{.spec.healthCheckExprs}{"\n"}'`.
2. **READ** the result: `kubectl -n $NAMESPACE get helmrelease $NEW_HR_NAME -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason}: {.message}{"\n"}{end}'`
   Expect `Ready=True` and `Released=True` after the adoption upgrade. In the controller log the upgrade must wait for the `Cluster`.
3. Negative control (optional, test cluster only, **WRITE**): change the CEL `current` expression to `status.phase == 'Never'`
   in a copy and apply it; the HelmRelease must stay `Ready=False` with a health check timeout. Revert it.
4. Note: the expressions apply to objects that the chart renders. If the cluster chart does not render the `Cluster`
   in this release (it might live in a sibling release), the check does nothing: confirm with `grep 'kind: Cluster' release-manifest.before.yaml`.

## Rollback

At any point before Check 3, to put the old delivery back:
1. **WRITE** suspend the new HelmRelease, then delete the ResourceSet (the HelmRelease stays by the prune guard), then delete the new HelmRelease while it is suspended (no uninstall):
   ```
   kubectl -n $NAMESPACE patch helmrelease $NEW_HR_NAME --type merge -p '{"spec":{"suspend":true}}'
   kubectl -n $NAMESPACE delete resourceset,resourcesetinputprovider $NEW_HR_NAME
   kubectl -n $NAMESPACE delete helmrelease $NEW_HR_NAME
   ```
2. **WRITE** re-create the old HelmRelease from `old-hr.yaml` (remove `status`, `resourceVersion`, `uid`, `suspend`). Its `releaseName` is the same, so it finds the
   release and runs one upgrade back.
3. If an upgrade failed and left the release in a bad state: the manifests set `upgrade.remediation.strategy: rollback`, so helm-controller rolls back by itself;
   otherwise `helm -n $NAMESPACE rollback $RELEASE_NAME <vN>` by hand. The Helm release secrets backed up in step 1 of the old-object section are the last resort.

## Findings (throwaway run, 2026-11-10)

Run on a GS management cluster with a throwaway `hello-world` release (3.2.3 installed by a plain HelmRelease,
adopted with 3.2.4 by `throwaway.yaml`). All objects were removed after the run. Check 2 and Check 4 did not run.

| Item | Result |
|---|---|
| Versions (helm-controller, flux-operator, chart) | helm-controller v1.4.5, flux-operator v0.62.1, source-controller v1.7.4; chart `hello-world` 3.2.3 -> 3.2.4 |
| Check 1: revision before -> after, uninstall seen? | Pass. `.v1` "Install complete" -> `.v2` "Upgrade complete", no uninstall, no fresh install. Log: `release not managed by controller: found existing release in storage`, then `running 'upgrade' action`. The pod was replaced only because the chart version changed its labels. |
| Check 2: CAPI UIDs/generations unchanged? Machines untouched? | Not run. |
| Check 3: HelmRelease and release survive ResourceSet delete? State of the orphaned HelmRelease? | Pass, with the prune guard on the HelmRelease and the OCIRepository. Both objects and the release survived, the pod was untouched, the HelmRelease stayed `Ready=True`. A re-applied ResourceSet took both objects back into its inventory with no new Helm revision. |
| Check 4: Ready=True? Time to Ready | Not run: helm-controller v1.4.5 has no `healthCheckExprs` / `waitStrategy` (not in the CRD). Needs >= v1.5.0. |
| Old object removal: what owned it, how suspended/deleted | Applied by hand. Suspend, then delete: no uninstall, release secret `.v1` kept. |
| Surprises | See below. |
| Changes needed in the PRD / migration procedure | See below. |

Surprises, all fixed in the manifests here unless noted:

1. flux-operator rejects a `dependsOn` entry with a `name` and no `namespace`:
   `an empty namespace may not be set when a resource name is provided`. The ResourceSet never gets ready.
   Fixed here and in the HelmApp render.
2. GS Kyverno policies `flux-multi-tenancy` and `flux-operator-multi-tenancy` deny a HelmRelease with no
   `spec.serviceAccountName` (or `spec.kubeConfig.secretRef`) and a ResourceSet with no `spec.serviceAccountName`,
   in every namespace except `flux-giantswarm`, `giantswarm` and `monitoring`. **Not fixed in the HelmApp render.**
   The spike used a ServiceAccount with the `admin` ClusterRole plus a Role for `helmreleases` and `ocirepositories`.
3. The `admin` ClusterRole does not include the Flux kinds, and the GS ClusterRole `write-flux-resources` has no
   `ocirepositories`. The ResourceSet ServiceAccount needs both kinds.
4. The chart default values can fail admission (the `hello-world` ingress class). Not a HelmApp problem.

Known gaps found while preparing (to confirm or drop): the PRD render of the HelmRelease has no `spec.interval`, which is required by the
HelmRelease CRD (`api/v2/helmrelease_types.go:60-64`); the manifests here set `interval: 5m`.
