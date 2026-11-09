# Protection defaults

`spec.protect` defaults to `true` for charts named `cluster-*` or `release-*`, `false` otherwise; any HelmApp can set it.

- Protected: every HelmRelease gets `fluxcd.controlplane.io/prune: disabled`. Flux Operator's ResourceSet skips resources with it when pruning and when the ResourceSet is deleted (`fluxcd.controlplane.io/prune` at fo059 `api/v1/common_types.go:32`, exclusions at `internal/controller/resourceset_controller.go:969-971` on delete and `:669` on stale GC). The HelmRelease and the Helm release stay as orphans.
- Protected `cluster-*` / `release-*` charts also get a default `healthCheckExprs` entry (CAPI `cluster.x-k8s.io/v1beta1` `Cluster`, Ready condition true) and `waitStrategy: poller`. CEL runs only with wait enabled and the poller strategy (helm-controller `api/v2/helmrelease_types.go:203-209`).
- `spec.healthCheckExprs` is passed to every HelmRelease on every chart. Entries add to the default; an entry with the same `apiVersion` and `kind` as the default replaces it. Setting any entry enables `waitStrategy: poller`.
- Prerequisite: helm-controller >= v1.5.0 (`healthCheckExprs`, `waitStrategy`).

## Known gap: orphaned HelmRelease loses its source

Only the HelmRelease carries the prune guard. The OCIRepository in the same ResourceSet does not, so deleting the HelmApp (or the ResourceSet) prunes it (`resourceset_controller.go:962-971`: delete with exclusion only for annotated objects). The orphaned HelmRelease keeps its `chartRef` to the gone OCIRepository. In helm-controller `getSource` returns NotFound (`internal/controller/helmrelease_controller.go:280,855-865`), the release is marked `Ready=False` with `ArtifactFailed` ("could not get Source object") and the error is returned, so it retries with backoff (`:296-298`). The installed Helm release is untouched, but no upgrade or drift correction happens until a source exists again; deleting the HelmRelease still uninstalls without the source (`reconcileReleaseDeletion`, `:508-535`). Not fixed: an option is to annotate the OCIRepository too, which is a decision for the user.

## Open: CAPI Cluster default for `release-*`

`cluster-<provider>` charts render the CAPI `Cluster` (`v1beta1`) via the shared `cluster` chart (`cluster/helm/cluster/templates/clusterapi/cluster.yaml:2-3`), so the default fits them. The `release-<provider>` chart source is not in the available clones, so it could not be verified from source. Helm's poller wait evaluates only resources in the release manifest: if `release-*` renders only nested HelmReleases or Apps and no `Cluster`, the default matches nothing and has no effect; it does not fail. Per the ticket it is applied to `release-*` as well, and needs a check against a rendered `release-aws`.
