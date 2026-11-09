# Renders a HelmApp: one RSIP, and one ResourceSet holding the OCIRepository and one HelmRelease per target.
oxr = option("params").oxr
spec = oxr.spec
name = oxr.metadata.name
ns = oxr.metadata.namespace
repo = spec.chart?.repository or "oci://gsoci.azurecr.io/charts/giantswarm"
chart_url = "${repo}/${spec.chart.name}"
GS_REPO = "oci://gsoci.azurecr.io/charts/giantswarm"
# Regexes as architect-orb verifies its own signatures: https://github.com/giantswarm/architect-orb/blob/main/docs/cosign-signing.md
# shortcut: matches any CircleCI project/pipeline, not only Giant Swarm's; pin the org id in the issuer once known.
_gs_verify = {
    provider = "cosign"
    matchOIDCIdentity = [{
        issuer = "^https://oidc\\.circleci\\.com"
        subject = "^https://circleci\\.com/api/v2/projects/[a-f0-9-]+/pipeline-definitions/[a-f0-9-]+$"
    }]
}
_verify = spec.chart?.verify or (_gs_verify if repo == GS_REPO else Undefined)
# RSIP OCIArtifactTag exports the input keys id, tag, digest; flux-operator renders << >> templates.
TAG = "<< inputs.tag | quote >>"
FLUX_CP = "fluxcd.controlplane.io/v1"

# Protection: cluster-* and release-* charts are protected unless spec.protect says otherwise.
_is_cluster_chart = spec.chart.name.startswith("cluster-") or spec.chart.name.startswith("release-")
_protect = spec.protect if spec.protect != Undefined else _is_cluster_chart
# shortcut: release-* gets the CAPI Cluster check too, as the ticket says; whether it fits every release-* chart is open (docs/protection.md).
_default_checks = [{
    apiVersion = "cluster.x-k8s.io/v1beta1"
    kind = "Cluster"
    current = "status.conditions.filter(e, e.type == 'Ready').all(e, e.status == 'True')"
}] if _protect and _is_cluster_chart else []
# A user entry for the same apiVersion and kind replaces the default, any other entry is added.
_user_checks = spec.healthCheckExprs or []
_checks = [d for d in _default_checks if not [u for u in _user_checks if u.apiVersion == d.apiVersion and u.kind == d.kind]] + _user_checks

_annot = lambda n: str -> {str:str} { {"krm.kcl.dev/composition-resource-name" = n} }

# valuesFrom layers, lowest to highest: derived cluster values, global, per target, derived user values; spec.values is applied last by Flux.
_values_from = lambda t -> [{str:}] {
    _derived = not t?.inCluster
    _cluster = [{kind = "ConfigMap", name = "${t.cluster}-cluster-values", optional = True}] if _derived else []
    _user = [{kind = "ConfigMap", name = "${t.cluster}-${name}-user-values", optional = True}, {kind = "Secret", name = "${t.cluster}-${name}-user-values", optional = True}] if _derived else []
    _cluster + (spec.valuesFrom or []) + (t.valuesFrom or []) + _user
}

_helmrelease = lambda t -> {str:} {
    _vf = _values_from(t)
    _values = merge_values(spec.values or {}, t.values or {})
    _cluster = MC if t.inCluster else t.cluster
    _deps = [{name = n} for n in spec.dependsOn?.static or []] + [{name = n.replace("%cluster%", _cluster)} for n in spec.dependsOn?.templated or []]
    {
        apiVersion = "helm.toolkit.fluxcd.io/v2"
        kind = "HelmRelease"
        metadata = {name = "${_cluster}-${name}", namespace = ns, **({annotations = {"fluxcd.controlplane.io/prune" = "disabled"}} if _protect else {})}
        spec = {
            interval = "5m"
            releaseName = spec.helmReleaseOverrides?.releaseName or name
            chartRef = {kind = "OCIRepository", name = name}
            if not t.inCluster:
                kubeConfig = {secretRef = {name = "${_cluster}-kubeconfig"}}
                targetNamespace = spec.namespace
                storageNamespace = spec.namespace
            if _deps:
                dependsOn = _deps
            install = {remediation = {retries = 10}}
            upgrade = {remediation = {retries = 10, strategy = "rollback"}}
            driftDetection = {mode = "warn"}
            # CEL checks run only with wait enabled (disableWait unset) and the poller strategy.
            if _checks:
                waitStrategy = {name = "poller"}
                healthCheckExprs = _checks
            if _vf:
                valuesFrom = _vf
            if _values:
                values = _values
        }
    }
}

_rsip = {
    apiVersion = FLUX_CP
    kind = "ResourceSetInputProvider"
    metadata = {name = name, namespace = ns, annotations = _annot("rsip")}
    spec = {
        type = "OCIArtifactTag"
        url = chart_url
        "filter" = {semver = spec.chart.version}
    }
}

_rset = {
    apiVersion = FLUX_CP
    kind = "ResourceSet"
    metadata = {name = name, namespace = ns, annotations = _annot("rset")}
    spec = {
        inputsFrom = [{kind = "ResourceSetInputProvider", name = name}]
        # Empty-input guard: exportedInputs is omitempty, so "empty" means absent. Without it the RSet prunes every HelmRelease.
        dependsOn = [{
            apiVersion = FLUX_CP
            kind = "ResourceSetInputProvider"
            name = name
            ready = True
            readyExpr = "has(status.exportedInputs) && size(status.exportedInputs) > 0"
        }]
        resources = [{
            apiVersion = "source.toolkit.fluxcd.io/v1"
            kind = "OCIRepository"
            metadata = {name = name, namespace = ns}
            spec = {interval = "5m", url = chart_url, ref = {tag = TAG}, **({"verify" = _verify} if _verify else {})}
        }] + [_helmrelease(t) for t in spec.targets.static]
    }
}

# Per-target HelmReleases are applied by the ResourceSet, not composed, so they are read as namespaced extra resources.
_hr_key = lambda t -> str { "hr-${t.cluster}" }
_hr_req = {
    apiVersion = "meta.krm.kcl.dev/v1alpha1"
    kind = "ExtraResources"
    requirements = {
        _hr_key(t) = {
            apiVersion = "helm.toolkit.fluxcd.io/v2"
            kind = "HelmRelease"
            matchName = "${t.cluster}-${name}"
            matchNamespace = ns
        } for t in spec.targets.static
    }
}

_ocds = option("params").ocds
_er = option("params")?.extraResources or {}
_exported = _ocds?.rsip?.Resource?.status?.exportedInputs or []
_hr = lambda t -> {str:} { (_er[_hr_key(t)] or [{}])[0]?.Resource or {} }
_ready_cond = lambda h -> [{str:}] { [c for c in (h.status?.conditions or []) if c.type == "Ready"] }
_target = lambda t -> {str:} {
    {
        cluster = t.cluster
        version = ((_hr(t).status?.history or [{}])[0]?.chartVersion) or ""
        ready = len([c for c in _ready_cond(_hr(t)) if c.status == "True"]) > 0
        message = (_ready_cond(_hr(t)) or [{}])[0]?.message or ""
    }
}
_targets = [_target(t) for t in spec.targets.static]

_status = {
    # The last running version stays visible while the guard holds, because it comes from the HelmReleases.
    version = (_exported or [{}])[0]?.tag or ([t.version for t in _targets if t.version] or [""])[0]
    message = "Waiting for the input provider." if not _ocds?.rsip else "" if _exported else "No chart version exported for \"${spec.chart.version}\" (no matching tag, or waiting for the schedule). Existing HelmReleases are kept."
    targets = _targets
}

_dxr = {**option("params").dxr, status = _status}

items = [_rsip, _rset, _hr_req, _dxr]
