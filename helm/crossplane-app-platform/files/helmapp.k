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

_annot = lambda n: str -> {str:str} { {"krm.kcl.dev/composition-resource-name" = n} }

_helmrelease = lambda t -> {str:} {
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
            spec = {interval = "5m", url = chart_url, ref = {tag = TAG}, **({"verify" = _verify} if _verify else {})}
        }] + [_helmrelease(t) for t in spec.targets.static]
    }
}

items = [_rsip, _rset]
