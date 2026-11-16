import copy
import json

import pytest

import wrap
from wrap import Stop


def converter_hr(name="acme01-ingress-nginx", ns="org-acme", remote=True):
    """A HelmRelease in the shape the App CR converter writes."""
    spec = {
        "chartRef": {"kind": "OCIRepository", "name": name, "namespace": ns},
        "install": {"remediation": {"retries": 3}},
        "interval": "10m",
        "releaseName": "ingress-nginx",
        "storageNamespace": "kube-system",
        "targetNamespace": "kube-system",
        "timeout": "10m",
        "upgrade": {"remediation": {"remediateLastFailure": True, "retries": 3}},
        "kubeConfig": {"secretRef": {"name": "acme01-kubeconfig"}},
        "valuesFrom": [
            {"kind": "ConfigMap", "name": "acme01-cluster-values", "valuesKey": "values", "optional": True},
            {"kind": "ConfigMap", "name": "acme01-ingress-nginx-user-values", "valuesKey": "values"},
            {"kind": "Secret", "name": "acme01-ingress-nginx-user-values", "valuesKey": "values"},
        ],
    }
    if not remote:
        for k in ("kubeConfig", "storageNamespace", "targetNamespace"):
            spec.pop(k)
        spec["serviceAccountName"] = "automation"
    return {"metadata": {"name": name, "namespace": ns}, "spec": spec,
            "status": {"history": [{"chartVersion": "3.2.1"}]}}


def ocirepo(url="oci://gsoci.azurecr.io/charts/giantswarm/ingress-nginx", tag="3.2.1"):
    return {"spec": {"url": url, "ref": {"tag": tag}}}


def test_case_a_same_name_remote():
    helmapp, case, warnings, _ = wrap.wrap(converter_hr(), ocirepo(), "ingress-nginx")
    assert case == "A"
    assert helmapp["metadata"] == {"name": "ingress-nginx", "namespace": "org-acme"}
    s = helmapp["spec"]
    assert s["chart"] == {"name": "ingress-nginx", "version": "3.2.1"}
    assert s["namespace"] == "kube-system"
    assert s["targets"] == {"static": [{"cluster": "acme01"}]}
    assert "helmReleaseOverrides" not in s  # release name equals the HelmApp name
    assert "valuesFrom" not in s  # all three layers are the ones the HelmApp adds by itself
    assert s["protect"] is True
    assert any("timeout" in w for w in warnings)
    assert not any("order" in w for w in warnings)


def test_case_b_suffix_name_keeps_release_name_and_other_layers():
    hr = converter_hr(name="ingress-nginx-acme01")
    hr["spec"]["valuesFrom"].insert(1, {"kind": "ConfigMap", "name": "extra", "valuesKey": "values"})
    hr["spec"]["suspend"] = True
    helmapp, case, warnings, _ = wrap.wrap(hr, ocirepo(), "nginx")
    assert case == "B"
    s = helmapp["spec"]
    assert s["helmReleaseOverrides"] == {"releaseName": "ingress-nginx"}
    # The user-values names use the HelmApp name, so the old ones stay as plain layers.
    assert [v["name"] for v in s["valuesFrom"]] == ["extra", "acme01-ingress-nginx-user-values",
                                                    "acme01-ingress-nginx-user-values"]
    assert any("suspended" in w for w in warnings)
    assert "suspend" not in s


def test_value_layer_order_change_is_reported():
    hr = converter_hr()
    hr["spec"]["valuesFrom"].append({"kind": "ConfigMap", "name": "extra"})
    _, _, warnings, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert any("order" in w for w in warnings)


def test_cluster_chart_in_cluster_copies_value_layers_unchanged():
    hr = converter_hr(name="acme01", remote=False)
    hr["spec"]["releaseName"] = "acme01"
    hr["spec"]["valuesFrom"] = [
        {"kind": "ConfigMap", "name": "acme01-cluster-values", "valuesKey": "values"},
        {"kind": "ConfigMap", "name": "cluster-app-installation-values", "valuesKey": "values"},
        {"kind": "Secret", "name": "acme01-userconfig", "valuesKey": "values"},
    ]
    hr["status"]["history"] = [{"chartVersion": "33.0.0"}]
    repo = ocirepo(url="oci://gsoci.azurecr.io/charts/giantswarm/release-aws", tag=">=33.0.0")
    helmapp, case, _, _ = wrap.wrap(hr, repo, "acme01", mc_name="graveler")
    assert case == "B"  # the MC HelmRelease is acme01, the HelmApp renders graveler-acme01
    s = helmapp["spec"]
    assert s["targets"] == {"static": [{"inCluster": True}]}
    assert s["namespace"] == "org-acme"
    assert s["chart"] == {"name": "release-aws", "version": "33.0.0"}
    assert s["helmReleaseOverrides"] == {"serviceAccountName": "automation"}
    assert s["valuesFrom"] == hr["spec"]["valuesFrom"]
    assert "values" not in s


def test_private_registry_and_custom_repository():
    repo = ocirepo(url="oci://registry.example.com/charts/app")
    repo["spec"]["secretRef"] = {"name": "pull"}
    helmapp, _, _, _ = wrap.wrap(converter_hr(), repo, "ingress-nginx")
    assert helmapp["spec"]["chart"] == {"name": "app", "repository": "oci://registry.example.com/charts",
                                        "version": "3.2.1", "secretRef": {"name": "pull"}}


def test_flux_default_release_name():
    hr = converter_hr()
    del hr["spec"]["releaseName"]
    helmapp, _, _, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert helmapp["spec"]["helmReleaseOverrides"] == {"releaseName": "kube-system-acme01-ingress-nginx"}


def test_dependson_same_namespace():
    hr = converter_hr()
    hr["spec"]["dependsOn"] = [{"name": "acme01-cert-manager"}]
    helmapp, _, _, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert helmapp["spec"]["dependsOn"] == {"static": ["acme01-cert-manager"]}


@pytest.mark.parametrize("change, message", [
    (lambda hr: hr["spec"].update(storageNamespace="other"), "storageNamespace"),
    (lambda hr: hr["spec"].update(chartRef={"kind": "HelmChart", "name": "x"}), "OCIRepository"),
    (lambda hr: hr["spec"].update(chart={"spec": {"chart": "x"}}), "inline spec.chart"),
    (lambda hr: hr["spec"].update(kubeConfig={"secretRef": {"name": "acme01-kc"}}), "<cluster>-kubeconfig"),
    (lambda hr: hr["spec"].update(kubeConfig={"configMapRef": {"name": "kc"}}), "only secretRef.name"),
    (lambda hr: hr["spec"].update(kubeConfig={"secretRef": {"name": "acme01-kubeconfig", "key": "k"}}), "only secretRef.name"),
    (lambda hr: hr["spec"].update(dependsOn=[{"name": "x", "namespace": "other"}]), "another namespace"),
])
def test_stop_conditions(change, message):
    hr = converter_hr()
    change(hr)
    with pytest.raises(Stop, match=message):
        wrap.wrap(hr, ocirepo(), "ingress-nginx")


def test_unknown_spec_fields_go_to_helmreleaseoverrides():
    hr = converter_hr()
    hr["spec"]["postRenderers"] = [{"kustomize": {"patches": []}}]
    helmapp, _, warnings, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert helmapp["spec"]["helmReleaseOverrides"] == {"postRenderers": [{"kustomize": {"patches": []}}]}
    assert any("postRenderers" in w for w in warnings)


def test_values_from_target_path_is_kept():
    hr = converter_hr()
    item = {"kind": "Secret", "name": "x", "targetPath": "a.b"}
    hr["spec"]["valuesFrom"].append(item)
    helmapp, _, _, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert item in helmapp["spec"]["valuesFrom"]


def test_ocirepository_verify_maps_to_chart_verify():
    repo = ocirepo()
    verify = {"provider": "cosign", "matchOIDCIdentity": [{"issuer": "i", "subject": "s"}]}
    repo["spec"]["verify"] = verify
    helmapp, _, _, _ = wrap.wrap(converter_hr(), repo, "ingress-nginx")
    assert helmapp["spec"]["chart"]["verify"] == verify
    repo["spec"]["verify"] = {"provider": "cosign", "secretRef": {"name": "key"}}
    helmapp, _, _, _ = wrap.wrap(converter_hr(), repo, "ingress-nginx")
    assert helmapp["spec"]["chart"]["verify"] == {"provider": "cosign", "secretRef": {"name": "key"}}


@pytest.mark.parametrize("spec_change, message", [
    ({"certSecretRef": {"name": "ca"}}, "certSecretRef"),
    ({"provider": "azure"}, "provider"),
    ({"insecure": True}, "insecure"),
    ({"verify": {"provider": "notation"}}, "verify must be provider cosign"),
    ({"verify": {"provider": "cosign", "other": 1}}, "verify must be provider cosign"),
])
def test_ocirepository_unmapped_fields_stop(spec_change, message):
    repo = ocirepo()
    repo["spec"].update(spec_change)
    with pytest.raises(Stop, match=message):
        wrap.wrap(converter_hr(), repo, "ingress-nginx")


def test_in_cluster_needs_mc_name_and_own_namespace():
    hr = converter_hr(remote=False)
    with pytest.raises(Stop, match="MC name"):
        wrap.wrap(hr, ocirepo(), "x")
    hr["spec"]["targetNamespace"] = "kube-system"
    with pytest.raises(Stop, match="in-cluster"):
        wrap.wrap(hr, ocirepo(), "x", mc_name="mc")


def test_version_from_tag_when_no_history():
    hr = converter_hr()
    del hr["status"]
    helmapp, _, _, _ = wrap.wrap(hr, ocirepo(tag="3.0.0"), "ingress-nginx")
    assert helmapp["spec"]["chart"]["version"] == "3.0.0"


def suspended_hr(annotation=wrap.KUSTOMIZE_PRUNE):
    hr = converter_hr(name="ingress-nginx-acme01")
    hr["spec"]["suspend"] = True
    hr["metadata"]["annotations"] = {annotation: "disabled"}
    return hr


@pytest.mark.parametrize("annotation", [wrap.KUSTOMIZE_PRUNE, wrap.OPERATOR_PRUNE])
def test_deletable_when_suspended_and_guarded(annotation):
    wrap.check_deletable(suspended_hr(annotation))


@pytest.mark.parametrize("change, message", [
    (lambda hr: hr["spec"].pop("suspend"), "not suspended"),
    (lambda hr: hr["spec"].update(suspend="true"), "not suspended"),
    (lambda hr: hr["metadata"].pop("annotations"), "annotation"),
    (lambda hr: hr["metadata"].update(deletionTimestamp="now"), "being deleted"),
])
def test_not_deletable(change, message):
    hr = suspended_hr()
    change(hr)
    with pytest.raises(Stop, match=message):
        wrap.check_deletable(hr)


def test_delete_suspended_never_calls_delete_on_stop(monkeypatch, capsys):
    hr = suspended_hr()
    hr["spec"]["suspend"] = False
    calls = []

    def fake_kubectl(context, *args):
        calls.append(args)
        return json.dumps(copy.deepcopy(hr))

    monkeypatch.setattr(wrap, "kubectl", fake_kubectl)
    assert wrap.main(["delete-suspended", "--context", "c", "-n", "org-acme", "ingress-nginx-acme01", "--yes"]) == 2
    assert all("delete" not in a for a in calls)
    assert "not suspended" in capsys.readouterr().err


def test_delete_suspended_dry_run_and_yes(monkeypatch, capsys):
    hr = suspended_hr()
    calls = []

    def fake_kubectl(context, *args):
        calls.append(args)
        return "deleted\n" if "delete" in args else json.dumps(hr)

    monkeypatch.setattr(wrap, "kubectl", fake_kubectl)
    args = ["delete-suspended", "--context", "c", "-n", "org-acme", "ingress-nginx-acme01"]
    assert wrap.main(args) == 0
    assert not any("delete" in a for a in calls)
    assert "dry run" in capsys.readouterr().out
    assert wrap.main(args + ["--yes"]) == 0
    assert any("delete" in a for a in calls)


def test_plan_reads_mc_name_for_in_cluster(monkeypatch, capsys):
    hr = converter_hr(name="acme01", remote=False)
    hr["spec"]["releaseName"] = "acme01"
    objects = {"helmrelease.helm.toolkit.fluxcd.io": hr, "ocirepository.source.toolkit.fluxcd.io": ocirepo(),
               "configmap": {"data": {"NAME": "graveler"}}}
    monkeypatch.setattr(wrap, "kubectl", lambda context, *a: json.dumps(objects[a[3]]))
    assert wrap.main(["plan", "--context", "c", "-n", "org-acme", "acme01", "--app", "acme01"]) == 0
    out = capsys.readouterr()
    assert "kind: HelmApp" in out.out
    assert "Case B" in out.err and "graveler-acme01" in out.err
    assert "delete-suspended" in out.err


def test_version_drops_the_flux_oci_digest_suffix():
    # helm-controller writes '<chart version>+<first 12 hex of the OCI digest>'; the registry tag has no suffix.
    hr = converter_hr()
    hr["status"]["history"] = [{"chartVersion": "2.11.0+44ca5d53b7f2",
                                "ociDigest": "sha256:44ca5d53b7f2d130d3e63df7d8048aac7cf09c5521fedd3b3ca7b8c3b94ff6ad"}]
    helmapp, _, _, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert helmapp["spec"]["chart"]["version"] == "2.11.0"


def test_version_keeps_build_metadata_of_the_chart():
    hr = converter_hr()
    hr["status"]["history"] = [{"chartVersion": "2.11.0+build.7", "ociDigest": "sha256:44ca5d53b7f2d130"}]
    helmapp, _, _, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert helmapp["spec"]["chart"]["version"] == "2.11.0+build.7"


def test_case_b_steps_remove_from_git_before_the_suspended_delete():
    s = wrap.steps("B", "ns", "old", "app", "mc", "old")
    assert [x.split(":")[0] for x in s] == ["WRITE (git)", "READ", "WRITE (git)", "WRITE", "READ", "WRITE (git)", "READ",
                                             "WRITE (git)"]
    assert "remove HelmRelease ns/old from git" in s[2]
    assert s[3].startswith("WRITE: helmapp-wrap delete-suspended --context <mc-context> -n ns old --yes")
    assert "add the HelmApp ns/app" in s[5]
    assert s[-1].endswith("remove the unused OCIRepository ns/old from git")


def test_case_a_steps():
    s = wrap.steps("A", "ns", "mc-app", "app", "mc", "app")
    assert [x.split(":")[0] for x in s] == ["WRITE (git)", "READ", "WRITE (git)", "READ", "WRITE (git)", "READ",
                                             "WRITE (git)"]
    assert "prune" in s[-1] and "OCIRepository ns/app" in s[-1]


def test_wrap_returns_the_cluster():
    assert wrap.wrap(converter_hr(), ocirepo(), "ingress-nginx")[3] == "acme01"
    assert wrap.wrap(converter_hr(remote=False), ocirepo(), "x", mc_name="mc")[3] == "mc"
