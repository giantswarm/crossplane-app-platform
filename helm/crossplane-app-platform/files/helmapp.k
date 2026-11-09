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

_helmrelease = lambda t -> {str:} {
    _cluster = MC if t.inCluster else t.cluster
    _deps = [{name = n} for n in spec.dependsOn?.static or []] + [{name = n.replace("%cluster%", _cluster)} for n in spec.dependsOn?.templated or []]
    {
        apiVersion = "helm.toolkit.fluxcd.io/v2"
        kind = "HelmRelease"
        metadata = {name = "${_cluster}-${name}", namespace = ns}
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
