[![CircleCI](https://dl.circleci.com/status-badge/img/gh/giantswarm/crossplane-app-platform/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/giantswarm/crossplane-app-platform/tree/main)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/giantswarm/crossplane-app-platform/badge)](https://securityscorecards.dev/viewer/?uri=github.com/giantswarm/crossplane-app-platform)

[Guide about how to manage an app on Giant Swarm](https://handbook.giantswarm.io/docs/dev-and-releng/app-developer-processes/adding_app_to_appcatalog/)

## Creating a repository from this template

A repository is created from this template by the repository set-up engine (`devctl`), which replaces the
placeholders below, renames the chart directory `helm/crossplane-app-platform` and pushes the result as the first commit. When
copying by hand, rename the chart directory and replace them yourself
(`devctl replace -i 'crossplane-app-platform' <name> --ignore '.git/**' '**'`, likewise for the other two).

| Placeholder | Where | Replaced with |
|---|---|---|
| `crossplane-app-platform` | the chart directory `helm/crossplane-app-platform`, `Chart.yaml`, `values.yaml`, `.abs/main.yaml`, `CHANGELOG.md`, this README | the repository name |
| `honeybadger` | the `io.giantswarm.application.team` annotation in `Chart.yaml` | the owning team's short name, e.g. `shield` for team-shield |
| `https://github.com/giantswarm/crossplane-app-platform` | this README | the upstream Helm repository the chart is based on |

The tokens are braced, unlike `REPOSITORY_NAME` in the Go service template: a Go module path may not contain
braces, so that template's token is brace-less. The engine's replacement pass handles both forms, so a repository
is created from either template the same way; only when copying by hand does the pattern differ (`crossplane-app-platform`
here, `REPOSITORY_NAME` there).

The chart ships with the default Giant Swarm icon (`https://s.giantswarm.io/app-icons/giantswarm/1/light.svg`),
so that the first build passes the icon checks. It is a default, not a placeholder: replace it with the app's
own icon by adding it to [web-assets](https://github.com/giantswarm/web-assets) and setting the final URL as
`icon` in `Chart.yaml`.

Remove this section from the README of the created repository.

# crossplane-app-platform chart

Giant Swarm offers a crossplane-app-platform App which can be installed in workload clusters.
Here, we define the crossplane-app-platform chart with its templates and default configuration.

**What is this app?**

**Why did we add it?**

**Who can use it?**

## Installing

There are several ways to install this app onto a workload cluster.

- [Using GitOps to instantiate the App](https://docs.giantswarm.io/tutorials/continuous-deployment/apps/add-appcr/)
- By creating an [App resource](https://docs.giantswarm.io/reference/platform-api/crd/apps.application.giantswarm.io) using the platform API as explained in [Getting started with App Platform](https://docs.giantswarm.io/tutorials/fleet-management/app-platform/).

## Configuring

### values.yaml

**This is an example of a values file you could upload using our web interface.**

```yaml
# values.yaml

```

### Sample App CR and ConfigMap for the management cluster

If you have access to the Kubernetes API on the management cluster, you could create the App CR and ConfigMap directly.

Here is an example that would install the app to workload cluster `abc12`:

```yaml
# appCR.yaml

```

```yaml
# user-values-configmap.yaml

```

See our [full reference on how to configure apps](https://docs.giantswarm.io/tutorials/fleet-management/app-platform/app-configuration/) for more details.

## Compatibility

This app has been tested to work with the following workload cluster release versions:

- _add release version_

## Limitations

Some apps have restrictions on how they can be deployed.
Not following these limitations will most likely result in a broken deployment.

- _add limitation_

## HelmApp

`helm/crossplane-app-platform` packages the HelmApp XRD, Composition (function-kcl source in
`helm/crossplane-app-platform/files/helmapp.k`) and the aggregated ClusterRole. It uses the `function-kcl` Function the platform installs on every MC (management-cluster-bases `extras/crossplane/functions`); the golden tests use the same package.
Nothing is deployed from here. Golden tests: install the Crossplane v2 CLI as `bin/crossplane`
(https://cli.crossplane.io/stable/current/bin/linux_amd64/crossplane), then `make test-golden` (`UPDATE=1` rewrites
expected files) and `make test-cel` (XRD rules, offline). CEL question: see [docs/xrd-cel.md](docs/xrd-cel.md). Move an existing HelmRelease under a HelmApp: see [docs/migration.md](docs/migration.md).

## Credit

- https://github.com/giantswarm/crossplane-app-platform
