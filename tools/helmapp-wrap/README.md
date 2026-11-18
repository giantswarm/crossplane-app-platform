# helmapp-wrap

Moves one existing Flux `HelmRelease` under a `HelmApp` without a reinstall. The full procedure, the checks and the
rollback are in [docs/migration.md](../../docs/migration.md); the HelmApp fields are in
[docs/helmapp.md](../../docs/helmapp.md).

## Usage

Needs `uv` and a kube context for the MC that holds the HelmRelease.

```
uv run --directory tools/helmapp-wrap helmapp-wrap plan --context <mc-ctx> -n <ns> <helmrelease> --app <app> [-o helmapp.yaml]
uv run --directory tools/helmapp-wrap helmapp-wrap delete-suspended --context <mc-ctx> -n <ns> <helmrelease> [--yes]
```

- `plan` is read-only. It reads the HelmRelease, its OCIRepository and, for an in-cluster HelmRelease, the MC name
  (ConfigMap `flux-giantswarm/management-cluster-metadata`). It writes the HelmApp manifest to stdout (or to `-o`),
  and prints to stderr: the case (A or B), the warnings, the live guard state and the numbered steps.
- `delete-suspended` is the only cluster write (Case B step 4, rollback step 3). It deletes the HelmRelease only when
  `spec.suspend` is `true`, the object is not being deleted and it has a prune guard annotation. Without `--yes` it
  only prints the command it would run.

`--app` is the HelmApp name. It sets the new HelmRelease name, `<cluster>-<app>`, and the default Helm release name,
`<app>`. Pick the name the chart is known by, usually the chart name; for a cluster chart, the cluster name.

The tool runs only `delete-suspended`. Every git step stays manual, as the tool does not know the git source of the
HelmRelease. Do the READ checks of docs/migration.md yourself; the tool does not run `helm history` on the workload
cluster.

Exit codes: 0 OK, 1 a `kubectl` call failed, 2 a stop condition (a `stop:` line on stderr).

## Case A and Case B

- Case A: the HelmRelease is already named `<cluster>-<app>`. The ResourceSet adopts the same object. No Helm action
  runs.
- Case B: any other name. The old HelmRelease is suspended and deleted (guarded, so no uninstall), then the new
  HelmRelease `<cluster>-<app>` adopts the Helm release with one `helm upgrade`.

## Example: Case A

The HelmRelease `org-acme/acme01-ingress-nginx` installs `ingress-nginx` 3.1.0 on `acme01`:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: acme01-ingress-nginx
  namespace: org-acme
spec:
  chartRef: {kind: OCIRepository, name: acme01-ingress-nginx}
  releaseName: ingress-nginx
  serviceAccountName: automation
  kubeConfig: {secretRef: {name: acme01-kubeconfig}}
  targetNamespace: kube-system
  storageNamespace: kube-system
  interval: 10m
  timeout: 10m
  valuesFrom:
    - {kind: ConfigMap, name: acme01-cluster-values, optional: true}
    - {kind: ConfigMap, name: acme01-ingress-nginx-user-values, optional: true}
  values:
    controller: {replicaCount: 2}
```

```
$ helmapp-wrap plan --context mc01 -n org-acme acme01-ingress-nginx --app ingress-nginx
```

stdout:

```yaml
apiVersion: apps.giantswarm.io/v1alpha1
kind: HelmApp
metadata:
  name: ingress-nginx
  namespace: org-acme
spec:
  chart:
    name: ingress-nginx
    version: 3.1.0
  namespace: kube-system
  targets:
    static:
    - cluster: acme01
  helmReleaseOverrides:
    serviceAccountName: automation
  values:
    controller:
      replicaCount: 2
  protect: true
```

stderr:

```
Case A: HelmRelease org-acme/acme01-ingress-nginx -> HelmApp org-acme/ingress-nginx (new HelmRelease acme01-ingress-nginx)
warning: these fields change to the HelmApp defaults: interval, timeout
live: suspend=False kustomize.toolkit.fluxcd.io/prune=None
1. WRITE (git): add kustomize.toolkit.fluxcd.io/prune: disabled to HelmRelease org-acme/acme01-ingress-nginx; let the Kustomization apply it
2. READ: helmapp-wrap plan checks the annotation again; it must be on the live object
3. WRITE (git): remove HelmRelease org-acme/acme01-ingress-nginx from git
4. READ: HelmRelease org-acme/acme01-ingress-nginx is still there and Ready=True
5. WRITE (git): add the HelmApp org-acme/ingress-nginx
6. READ: the HelmApp is Ready=True, the HelmRelease has the ResourceSet labels, helm history has no uninstall
7. WRITE (git): remove the unused OCIRepository org-acme/acme01-ingress-nginx from git
```

What happened to the input:

- The version comes from the last deployed chart version (`status.history[0]`), without the `+digest` suffix, else
  from the OCIRepository tag. It is pinned. Change it to a range after the move if you want upgrades.
- `releaseName: ingress-nginx` equals `<app>`, so it is not in the overrides.
- The two derived values layers (`acme01-cluster-values`, `acme01-ingress-nginx-user-values`) are removed: the
  HelmApp adds them itself.
- `interval: 10m` and `timeout: 10m` are not copied. To keep the timeout, add `timeout: 10m` to
  `helmReleaseOverrides` before you commit.
- `protect: true` is always set, so a mistake in the move cannot uninstall the release. Set it to `false` later if you
  want.
- `live:` shows the guard state of the live object. In step 2 run `plan` again: it must show
  `kustomize.toolkit.fluxcd.io/prune=disabled` before you go on.

## Example: Case B

The HelmRelease `org-acme/ingress-nginx-acme01` has another name and a post-renderer:

```yaml
spec:
  chartRef: {kind: OCIRepository, name: ingress-nginx-acme01}
  releaseName: ingress-nginx
  serviceAccountName: automation
  kubeConfig: {secretRef: {name: acme01-kubeconfig}}
  targetNamespace: kube-system
  storageNamespace: kube-system
  postRenderers:
    - kustomize:
        patches:
          - target: {kind: Deployment}
            patch: |
              - op: add
                path: /metadata/labels/team
                value: acme
```

```
$ helmapp-wrap plan --context mc01 -n org-acme ingress-nginx-acme01 --app ingress-nginx -o ingress-nginx.yaml
Case B: HelmRelease org-acme/ingress-nginx-acme01 -> HelmApp org-acme/ingress-nginx (new HelmRelease acme01-ingress-nginx)
warning: these fields go to helmReleaseOverrides: postRenderers
live: suspend=False kustomize.toolkit.fluxcd.io/prune=None
1. WRITE (git): add kustomize.toolkit.fluxcd.io/prune: disabled and spec.suspend: true to HelmRelease org-acme/ingress-nginx-acme01
2. READ: .spec.suspend is true and the annotation is on the live object
3. WRITE (git): remove HelmRelease org-acme/ingress-nginx-acme01 from git
4. WRITE: helmapp-wrap delete-suspended --context <mc-context> -n org-acme ingress-nginx-acme01 --yes (refuses when it is not suspended)
5. READ: the Helm release secrets are still there and helm history has the same last revision
6. WRITE (git): add the HelmApp org-acme/ingress-nginx
7. READ: HelmRelease org-acme/acme01-ingress-nginx runs one upgrade, helm history has no uninstall, the HelmApp is Ready=True
8. WRITE (git): remove the unused OCIRepository org-acme/ingress-nginx-acme01 from git
```

`ingress-nginx.yaml`:

```yaml
apiVersion: apps.giantswarm.io/v1alpha1
kind: HelmApp
metadata:
  name: ingress-nginx
  namespace: org-acme
spec:
  chart:
    name: ingress-nginx
    version: 3.1.0
  namespace: kube-system
  targets:
    static:
    - cluster: acme01
  helmReleaseOverrides:
    serviceAccountName: automation
    postRenderers:
    - kustomize:
        patches:
        - patch: "- op: add\n  path: /metadata/labels/team\n  value: acme"
          target:
            kind: Deployment
  protect: true
```

Step 4: run it without `--yes` first, to see what it deletes.

```
$ helmapp-wrap delete-suspended --context mc01 -n org-acme ingress-nginx-acme01
dry run, would run: kubectl --context mc01 -n org-acme delete helmrelease.helm.toolkit.fluxcd.io ingress-nginx-acme01
$ helmapp-wrap delete-suspended --context mc01 -n org-acme ingress-nginx-acme01 --yes
```

It stops (exit code 2) when the HelmRelease is not suspended, is already being deleted, or has no
`kustomize.toolkit.fluxcd.io/prune: disabled` (or `fluxcd.controlplane.io/prune: disabled`) annotation:

```
stop: HelmRelease org-acme/ingress-nginx-acme01 is not suspended: a delete uninstalls the release
```

## Example: a cluster chart

A cluster chart HelmRelease lives on the MC (no `kubeConfig`) and is named after the cluster. Use the cluster name as
`--app`:

```yaml
metadata:
  name: acme01
  namespace: org-acme
spec:
  chartRef: {kind: OCIRepository, name: acme01}   # oci://gsoci.azurecr.io/charts/giantswarm/release-aws, tag 2.4.0
  releaseName: acme01
  serviceAccountName: automation
  valuesFrom:
    - {kind: ConfigMap, name: acme01-cluster-app-installation-values, valuesKey: values}
    - {kind: ConfigMap, name: acme01-userconfig}
```

```
$ helmapp-wrap plan --context mc01 -n org-acme acme01 --app acme01
```

```yaml
apiVersion: apps.giantswarm.io/v1alpha1
kind: HelmApp
metadata:
  name: acme01
  namespace: org-acme
spec:
  chart:
    name: release-aws
    version: 2.4.0
  namespace: org-acme
  targets:
    static:
    - inCluster: true
  helmReleaseOverrides:
    serviceAccountName: automation
  valuesFrom:
  - kind: ConfigMap
    name: acme01-cluster-app-installation-values
    valuesKey: values
  - kind: ConfigMap
    name: acme01-userconfig
  protect: true
```

```
Case B: HelmRelease org-acme/acme01 -> HelmApp org-acme/acme01 (new HelmRelease mc01-acme01)
live: suspend=False kustomize.toolkit.fluxcd.io/prune=None
1. WRITE (git): add kustomize.toolkit.fluxcd.io/prune: disabled and spec.suspend: true to HelmRelease org-acme/acme01
...
8. WRITE (git): add kustomize.toolkit.fluxcd.io/prune: disabled to OCIRepository org-acme/acme01, then remove it from git
```

The new HelmRelease name is `<mc>-<app>` (`mc01-acme01`), so a cluster chart is usually Case B. The last step guards
the old OCIRepository too, as a cluster chart must not lose its source by accident. The `valuesFrom` entries stay as
they are: an in-cluster target gets no derived layers.

## Warnings

A warning does not stop the tool. Read each one before you commit the HelmApp.

| Warning | What to do |
|---|---|
| `these fields change to the HelmApp defaults: ...` | Fields from `interval`, `timeout`, `install`, `upgrade`, `rollback`, `uninstall`, `test`, `driftDetection`, `maxHistory`, `persistentClient` are not copied. Add the ones you need to `helmReleaseOverrides` (or set `spec.driftDetection`). |
| `these fields go to helmReleaseOverrides: ...` | Every other HelmRelease field is copied there and deep-merged into the new HelmRelease. Check that it still makes sense. |
| `the valuesFrom order changes: ...` | The derived layers were in another position. The HelmApp order can give a different result when two layers set the same key. |
| `a removed valuesFrom layer has a custom valuesKey; ...` | The HelmApp reads the derived layer from the default key. Move the values to that key. |
| `the HelmRelease is suspended; the HelmApp is not ...` | The HelmApp renders it not suspended, unless you set `spec.suspend`. |

## Stop conditions

`plan` exits with code 2 and a `stop:` line when the HelmRelease cannot move safely:

- the chart is inline (`spec.chart`), or `chartRef` is not an OCIRepository, or the OCIRepository is in another
  namespace;
- the OCIRepository has a field the HelmApp cannot express (for example `proxySecretRef` or `insecure`), or its `verify` provider is
  not cosign;
- `kubeConfig` is not only `secretRef.name`, or the Secret is not `<cluster>-kubeconfig`;
- `targetNamespace` differs from `storageNamespace`, or an in-cluster HelmRelease uses a namespace other than its own;
- a `dependsOn` entry is in another namespace;
- the default Helm release name is longer than 53 characters;
- the HelmRelease has no deployed version.

Fix the HelmRelease in git first (for example, move the OCIRepository), or keep it as a plain HelmRelease.

## Tests

`make test-wrap`.
