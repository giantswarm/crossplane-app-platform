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
    helmapp, case, warnings = wrap.wrap(converter_hr(), ocirepo(), "ingress-nginx")
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
    helmapp, case, warnings = wrap.wrap(hr, ocirepo(), "nginx")
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
    _, _, warnings = wrap.wrap(hr, ocirepo(), "ingress-nginx")
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
    helmapp, case, _ = wrap.wrap(hr, repo, "acme01", mc_name="graveler")
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
    helmapp, _, _ = wrap.wrap(converter_hr(), repo, "ingress-nginx")
    assert helmapp["spec"]["chart"] == {"name": "app", "repository": "oci://registry.example.com/charts",
                                        "version": "3.2.1", "secretRef": {"name": "pull"}}


def test_flux_default_release_name():
    hr = converter_hr()
    del hr["spec"]["releaseName"]
    helmapp, _, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert helmapp["spec"]["helmReleaseOverrides"] == {"releaseName": "kube-system-acme01-ingress-nginx"}


def test_dependson_same_namespace():
    hr = converter_hr()
    hr["spec"]["dependsOn"] = [{"name": "acme01-cert-manager"}]
    helmapp, _, _ = wrap.wrap(hr, ocirepo(), "ingress-nginx")
    assert helmapp["spec"]["dependsOn"] == {"static": ["acme01-cert-manager"]}


@pytest.mark.parametrize("change, message", [
    (lambda hr: hr["spec"].update(storageNamespace="other"), "storageNamespace"),
    (lambda hr: hr["spec"].update(chartRef={"kind": "HelmChart", "name": "x"}), "OCIRepository"),
    (lambda hr: hr["spec"].update(postRenderers=[{}]), "postRenderers"),
    (lambda hr: hr["spec"].update(kubeConfig={"secretRef": {"name": "acme01-kc"}}), "<cluster>-kubeconfig"),
    (lambda hr: hr["spec"].update(dependsOn=[{"name": "x", "namespace": "other"}]), "another namespace"),
    (lambda hr: hr["spec"]["valuesFrom"].append({"kind": "Secret", "name": "x", "targetPath": "a.b"}), "targetPath"),
])
def test_stop_conditions(change, message):
    hr = converter_hr()
    change(hr)
    with pytest.raises(Stop, match=message):
        wrap.wrap(hr, ocirepo(), "ingress-nginx")


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
    helmapp, _, _ = wrap.wrap(hr, ocirepo(tag="3.0.0"), "ingress-nginx")
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
