# HelmApp reference

A `HelmApp` (`apps.giantswarm.io/v1alpha1`, namespaced) installs one Helm chart from an OCI registry on one or more
clusters. You write the HelmApp; the platform renders and owns the Flux objects. Do not edit the rendered objects:
the next reconcile puts them back.

For one HelmApp `<app>` in namespace `<ns>` the platform renders:

| Object | Name | What it does |
|---|---|---|
| `ResourceSetInputProvider` (RSIP), type `OCIArtifactTag` | `<app>` | Lists the chart tags, picks the newest tag that matches `chart.version`, inside the schedule windows |
| `ResourceSet` | `<app>` | Applies the objects below with the tag the RSIP exports |
| `OCIRepository` | `<app>` | Pulls the chart at that tag (`interval: 5m`) |
| `HelmRelease`, one per target | `<cluster>-<app>` | Installs the chart on the target cluster (`interval: 5m`) |

All of them are in `<ns>`. For an `inCluster` target, `<cluster>` is the name of the management cluster (MC).

## Minimal example

```yaml
apiVersion: apps.giantswarm.io/v1alpha1
kind: HelmApp
metadata:
  name: hello-world
  namespace: org-acme
spec:
  chart:
    name: hello-world
    version: ">=2.0.0 <3.0.0"
  namespace: hello-world
  targets:
    static:
      - cluster: acme01
```

This installs the newest `hello-world` 2.x chart from `oci://gsoci.azurecr.io/charts/giantswarm` on workload cluster
`acme01`, in namespace `hello-world`. When a new 2.x tag is pushed, the HelmApp upgrades to it at the next RSIP check.
Set an exact version (`version: 2.3.1`) to pin it.

## Fields

`spec.chart`, `spec.targets` and `spec.namespace` are required. All other fields are optional.

### `spec.chart`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string, required | | Chart name. No `/`. The chart URL is `<repository>/<name>`. |
| `repository` | string | `oci://gsoci.azurecr.io/charts/giantswarm` | OCI repository. Must start with `oci://`. |
| `version` | string, required | | An exact version (`1.2.3`) or a semver range (`>=1.2.0 <2.0.0`, `1.x`). The RSIP picks the newest matching tag. |
| `semverFilter` | string | | Regular expression on the tags, applied before `version`, the same as OCIRepository `spec.ref.semverFilter`. Use it to pick a tag family, for example `-rc` or `-dev` tags. |
| `secretRef.name` | string | | Registry credentials (a `kubernetes.io/dockerconfigjson` Secret) in the HelmApp namespace. Used by the RSIP and the OCIRepository. |
| `certSecretRef.name` | string | | TLS Secret in the HelmApp namespace: `ca.crt` for a private CA, and/or `tls.crt` and `tls.key` for a client certificate. Used by the RSIP and the OCIRepository. The RSIP trusts only the CAs in `ca.crt`; the OCIRepository adds them to the system CAs. So `ca.crt` must hold the CA that signs the registry certificate. |
| `serviceAccountName` | string | | ServiceAccount in the HelmApp namespace. The RSIP and the OCIRepository use its `imagePullSecrets` as registry credentials. This is not the impersonation account: for that, use `helmReleaseOverrides.serviceAccountName`. |
| `verify` | object | see below | Cosign verification of the chart. |

`verify`:

| Field | Type | Description |
|---|---|---|
| `provider` | `cosign` or `none`, required | `none` turns the check off for this HelmApp and takes no other field. |
| `secretRef.name` | string | Cosign public keys Secret (key-based signing). |
| `matchOIDCIdentity[]` | `{issuer, subject}` regexes | Keyless signing: the identities that are accepted. |

The `verify` object is copied to the OCIRepository `spec.verify`. When you do not set it, the platform decides: no
check, or, when the platform chart value `chartVerification.gsDefault` is `true`, the GS CircleCI keyless identity for
charts from the GS registry. That value is `false` today. `chart.verify` always wins over the platform default.

### `spec.targets.static[]`

1 to 100 entries. Each entry has exactly one of `cluster` and `inCluster`.

| Field | Type | Description |
|---|---|---|
| `cluster` | string, max 63 | A workload cluster in the HelmApp namespace. The HelmRelease uses the Secret `<cluster>-kubeconfig`. |
| `inCluster` | `true` | The MC itself. No kubeconfig. |
| `values` | object | Values for this target only, deep-merged over `spec.values`. |
| `valuesFrom[]` | list | ConfigMaps or Secrets for this target only. See [Values](#values). |

Rules:

- Each `cluster` can be a target only once.
- Only one `inCluster` target is allowed.
- `inCluster: true` and `cluster: <mc-name>` render the same HelmRelease name. The composition stops with
  `two targets render the same HelmRelease name ...`, and the HelmApp shows `Synced=False`. Remove one of them.
- An `inCluster` target needs the ConfigMap `flux-giantswarm/management-cluster-metadata` with the key `NAME`. All GS
  MCs have it.

What a target changes in its HelmRelease:

| | `cluster: <c>` | `inCluster: true` |
|---|---|---|
| Name | `<c>-<app>` | `<mc>-<app>` |
| `kubeConfig` | `secretRef.name: <c>-kubeconfig` | none |
| `targetNamespace`, `storageNamespace` | `spec.namespace` | none: the release goes to the HelmApp namespace |
| Derived values layers | yes | no |

### `spec.namespace`

Required, max 63 characters. The namespace on the target cluster for the chart's objects and the Helm release
Secrets. An `inCluster` target ignores it.

### Values

`spec.values` (object) and `spec.valuesFrom[]` apply to every target. Each `valuesFrom` entry:

| Field | Type | Description |
|---|---|---|
| `kind` | `ConfigMap` or `Secret`, required | |
| `name` | string, required | In the HelmApp namespace. |
| `valuesKey` | string | Key in the object, default `values.yaml`. |
| `targetPath` | string | Put the value at this path, not at the root. |
| `optional` | bool | When `true`, a missing object is not an error. |

The HelmRelease gets the layers in this order, lowest priority first:

1. `<cluster>-cluster-values` ConfigMap (optional, derived, remote targets only)
2. `spec.valuesFrom`
3. the target's `valuesFrom`
4. `<cluster>-<app>-user-values` ConfigMap and Secret (optional, derived, remote targets only)
5. `spec.values` deep-merged with the target's `values` (Flux applies inline values last)

Merge rules: maps merge key by key, lists are replaced as a whole, and `null` removes a key. Example: a target turns
off one key that `spec.values` sets.

```yaml
spec:
  values:
    ingress: {enabled: true, className: nginx}
    replicas: 2
  targets:
    static:
      - cluster: acme01
      - cluster: acme02
        values:
          ingress: {className: null}   # acme02 gets ingress.enabled=true only
          replicas: 3
```

The derived layers let you keep values out of the HelmApp: create `acme01-hello-world-user-values` in the HelmApp
namespace and the HelmRelease for `acme01` reads it. See [xr-null-values.md](xr-null-values.md) for how `null` is
kept through Crossplane.

### `spec.dependsOn`

| Field | Type | Description |
|---|---|---|
| `static[]` | strings | HelmRelease names (in the HelmApp namespace) copied into the `dependsOn` of every HelmRelease. |
| `templated[]` | strings | Names with `%cluster%` replaced by each target's cluster name. |

Example: `templated: ["%cluster%-cert-manager"]` makes the HelmRelease of each target wait for the HelmRelease of the
HelmApp `cert-manager` on the same cluster.

### `spec.schedule`

Upgrade windows. A new chart version is exported, so installed, only inside a window. See [schedule.md](schedule.md).

| Field | Type | Description |
|---|---|---|
| `windows[].cron` | string, required | Window start, cron syntax. |
| `windows[].timeZone` | string | IANA time zone, for example `Europe/Berlin`. Default UTC. |
| `windows[].window` | Go duration, required, min `4m` | Window length, for example `4h`. |
| `forceInstallOutsideWindow` | bool | Install the first version at once, outside a window. One time only, at creation. |

```yaml
spec:
  schedule:
    windows:
      - cron: "0 2 * * 1-5"      # weekdays 02:00
        timeZone: Europe/Berlin
        window: 3h
    forceInstallOutsideWindow: true
```

Outside a window, a new tag or a changed `chart.version` waits; the installed version keeps running.
`status.nextWindow` shows when the next window starts.

### `spec.driftDetection.mode`

`enabled`, `warn` (default) or `disabled`. Copied to every HelmRelease. `warn` reports drift in the HelmRelease
events; `enabled` also corrects it.

### `spec.suspend`

`true` suspends every rendered HelmRelease. The RSIP and the OCIRepository still run.

### `spec.protect`

Default `true` for charts named `cluster-*` or `release-*`, `false` for all others. When `true`, the HelmReleases and
the OCIRepository get the annotation `fluxcd.controlplane.io/prune: disabled`: when you delete the HelmApp or remove a
target, the HelmRelease stays and the release is not uninstalled. Set `protect: false` and wait until the annotation is
gone before you delete a protected HelmApp on purpose. See [protection.md](protection.md).

### `spec.healthCheckExprs[]`

CEL health checks for the objects the chart creates, copied to every HelmRelease (with `waitStrategy.name: poller`).

| Field | Type |
|---|---|
| `apiVersion`, `kind`, `current` | string, required |
| `inProgress`, `failed` | string |

This field needs helm-controller v1.5.0 or later. The platform turns it on with the chart value
`helmController.healthChecks`, which is `false` today; when it is off, a HelmApp with `healthCheckExprs` fails to
compose. When it is on, a protected `cluster-*` or `release-*` chart gets a default check: the CAPI `Cluster` is
`Ready`. An entry with the same `apiVersion` and `kind` replaces the default; other entries are added.

### `spec.helmReleaseOverrides`

The escape hatch for HelmRelease fields that the HelmApp does not have.

| Field | Description |
|---|---|
| `releaseName` | Helm release name. Default `<app>`. |
| `serviceAccountName` | Set on every HelmRelease and on the ResourceSet (impersonation). Not used for the registry; for that, use `chart.serviceAccountName`. Needed in customer namespaces when the original HelmRelease had one. |
| any other key | Deep-merged into the `spec` of every HelmRelease. `null` removes a key. |

```yaml
spec:
  helmReleaseOverrides:
    releaseName: ingress-nginx
    timeout: 15m
    install:
      crds: CreateReplace
    upgrade:
      remediation:
        strategy: uninstall     # replaces the default rollback
    postRenderers:
      - kustomize:
          patches:
            - target: {kind: Deployment}
              patch: |
                - op: add
                  path: /metadata/labels/team
                  value: acme
```

Use it with care: the platform does not check these keys, and a key that breaks the HelmRelease makes every target
fail.

## Defaults on every HelmRelease

| HelmRelease field | Value |
|---|---|
| `interval` | `5m` |
| `releaseName` | `<app>` |
| `chartRef` | the OCIRepository `<app>` |
| `install.remediation.retries` | `10` |
| `upgrade.remediation` | `retries: 10`, `strategy: rollback` |
| `driftDetection.mode` | `warn` |

Change them with `helmReleaseOverrides`.

## Status

```yaml
status:
  version: 2.3.1               # the tag the RSIP exported, else the last deployed version
  message: ""                  # why nothing is exported, when that is the case
  nextWindow: "2026-11-18T02:00:00+01:00"   # only while the schedule holds a run
  targets:
    - cluster: acme01
      version: 2.3.1           # last deployed chart version (without the +digest suffix)
      ready: true
      message: "Helm upgrade succeeded for release ..."
  conditions:
    - type: Ready
      status: "True"
    - type: Synced
      status: "True"
```

`Ready` is `True` only when all of these are true:

- The RSIP is Ready and runs the current `chart.version` and `chart.semverFilter`.
- The ResourceSet is Ready.
- Every target HelmRelease is Ready for its current generation and runs the exported tag.

`Synced=False` means that the composition failed. Its message gives the reason, for example a duplicate target.

When no tag matches `chart.version` (or the schedule holds the run), `message` says so and the existing HelmReleases
are kept as they are. They are not removed.

## Errors that the API server rejects

| Message | Cause |
|---|---|
| `chart.name must not contain a slash` | Put the path in `repository`. |
| `provider none takes no secretRef and no matchOIDCIdentity` | |
| `each cluster can be a target only once` | |
| `only one inCluster target is allowed` | |
| `set exactly one of cluster and inCluster` | |
| `window must be at least 4m ...` | |
| `should match '^oci://.+'` | `chart.repository` |

## More examples

Several clusters, one value per cluster:

```yaml
spec:
  chart: {name: ingress-nginx, version: "3.x"}
  namespace: kube-system
  values:
    controller: {replicaCount: 2}
  targets:
    static:
      - cluster: acme01
      - cluster: acme02
        values:
          controller: {replicaCount: 4}
```

A chart from another registry, with credentials, a private CA and keyless signatures:

```yaml
spec:
  chart:
    name: podinfo
    repository: oci://ghcr.io/stefanprodan/charts
    version: "6.x"
    secretRef: {name: ghcr-pull}
    certSecretRef: {name: registry-ca}
    verify:
      provider: cosign
      matchOIDCIdentity:
        - issuer: "^https://token.actions.githubusercontent.com$"
          subject: "^https://github.com/stefanprodan/podinfo.*$"
  namespace: podinfo
  targets:
    static:
      - cluster: acme01
```

Release candidates only:

```yaml
spec:
  chart:
    name: hello-world
    version: ">=2.4.0-0"
    semverFilter: ".*-rc.*"
```

A cluster chart on the MC (protected by default):

```yaml
apiVersion: apps.giantswarm.io/v1alpha1
kind: HelmApp
metadata:
  name: acme01
  namespace: org-acme
spec:
  chart: {name: cluster-aws, version: 3.4.0}
  namespace: org-acme
  targets:
    static:
      - inCluster: true
  valuesFrom:
    - kind: ConfigMap
      name: acme01-userconfig
      valuesKey: values
```

## Related

- [migration.md](migration.md): move an existing HelmRelease under a HelmApp, with
  [helmapp-wrap](../tools/helmapp-wrap/README.md).
- [customer-rbac.md](customer-rbac.md): who can create HelmApps.
- [protection.md](protection.md), [schedule.md](schedule.md), [xr-null-values.md](xr-null-values.md).
