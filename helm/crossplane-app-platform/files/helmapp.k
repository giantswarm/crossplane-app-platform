# Renders a HelmApp: one RSIP, and one ResourceSet holding the OCIRepository and one HelmRelease per target.
oxr = option("params").oxr
spec = oxr.spec
name = oxr.metadata.name
ns = oxr.metadata.namespace
repo = spec.chart?.repository or "oci://gsoci.azurecr.io/charts/giantswarm"
chart_url = "${repo}/${spec.chart.name}"
# RSIP OCIArtifactTag exports the input keys id, tag, digest; flux-operator renders << >> templates.
TAG = "<< inputs.tag | quote >>"
FLUX_CP = "fluxcd.controlplane.io/v1"

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
    {
        apiVersion = "helm.toolkit.fluxcd.io/v2"
        kind = "HelmRelease"
        metadata = {name = "${t.cluster}-${name}", namespace = ns}
        spec = {
            interval = "5m"
            releaseName = name
            chartRef = {kind = "OCIRepository", name = name}
            kubeConfig = {secretRef = {name = "${t.cluster}-kubeconfig"}}
            targetNamespace = spec.namespace
            storageNamespace = spec.namespace
            install = {remediation = {retries = 10}}
            upgrade = {remediation = {retries = 10, strategy = "rollback"}}
            driftDetection = {mode = "warn"}
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
        resources = [{
            apiVersion = "source.toolkit.fluxcd.io/v1"
            kind = "OCIRepository"
            metadata = {name = name, namespace = ns}
            spec = {interval = "5m", url = chart_url, ref = {tag = TAG}}
        }] + [_helmrelease(t) for t in spec.targets.static]
    }
}

items = [_rsip, _rset]
