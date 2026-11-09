# Customer RBAC and policy for HelmApp

## How Giant Swarm gives customers rights in `org-*` namespaces

Read from giantswarm/rbac-operator (default branch, 2026-11-09):

- Customer admin groups get a `RoleBinding` to the `cluster-admin` ClusterRole inside the org namespace
  (`service/controller/rbac/resource/namespaceauth/create.go:76-96`). A RoleBinding scopes every
  namespaced resource, `HelmApp` included, to that namespace. No chart change is needed for them.
- Read access is the `read-all` ClusterRole, built from API discovery: get/list/watch on every resource
  type except ConfigMap and Secret (`service/controller/defaultnamespace/resource/clusterroles/create.go:84-148`).
  A `HelmApp` is covered once its CRD exists.
- Subjects that customers bind themselves to the Kubernetes `admin`/`edit`/`view` roles are not covered by
  either. Crossplane's rbac-manager renders `crossplane:composite:<xrd>:aggregate-to-{edit,view}` for the XRD,
  but those aggregate only into Crossplane's own `crossplane-*` roles (crossplane v2.4 `internal/controller/rbac/definition/roles.go:95-135`).

## What the chart adds

`templates/clusterrole-customer.yaml`: three ClusterRoles aggregated into `admin`, `edit` and `view`.

| Role | Aggregates to | Rules |
|---|---|---|
| `crossplane-app-platform-helmapp-admin` | `admin` | `helmapps`, `helmapps/status`: `*` |
| `crossplane-app-platform-helmapp-edit` | `edit` | `helmapps`, `helmapps/status`: `*` |
| `crossplane-app-platform-helmapp-view` | `view` | `helmapps`, `helmapps/status`: get, list, watch |

Aggregated rules reach only where the customer's own RoleBinding does, so a binding in `org-x` gives HelmApp
rights in `org-x` and nowhere else. The roles grant no access to the composed Flux objects, Secrets or ConfigMaps.
Test: `make test-rbac`.

## Policy exception: none needed

Searched giantswarm/kyverno-policies, kyverno-policies-dx and kyverno-policies-ux (default branches, 2026-11-09):

- `restrict-usage-of-crossplane-crds` (dx) matches only `pkg.crossplane.io/v1 providers`. It does not touch
  HelmApp, the XRD, or the aggregated ClusterRoles.
- The only policies naming Flux kinds are the ux mutations `prepend-cluster-app-config-map(-hr)`. They mutate a
  `HelmRelease` in `org-*` (chartRef to a cluster-app OCIRepository) with `failurePolicy: Ignore`; they never reject.
  They apply to a composed HelmRelease if it points at a cluster-app chart.
- The kyverno-policies validating rules target Pods, ServiceAccounts, Services, Ingress, Namespaces and
  (Cluster)RoleBindings. None match RSIP, ResourceSet, OCIRepository or HelmRelease.

So the chart ships no `PolicyException`; `make test-rbac` asserts none is rendered. Re-check when a policy
that matches Flux kinds is added, or when the live Kyverno policy set differs from these repo defaults.

## Open items

- rbac-operator's `crossplaneauth` binds customer admin groups with a ClusterRoleBinding to a Crossplane role
  (`create.go:21-70`, name from config, not found in the chart values). If that role is `crossplane-edit`, it
  grants HelmApp edit in every namespace, not just `org-*`. Unverified; check on a cluster and with rbac-operator.
- Admission and the aggregation were not exercised on a cluster (none was touched).
