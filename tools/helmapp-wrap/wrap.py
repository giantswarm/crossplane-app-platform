"""helmapp-wrap: move a Flux HelmRelease under a HelmApp, as in docs/migration.md.

`plan` reads the live HelmRelease (and its OCIRepository), writes the HelmApp manifest and prints the steps of
Case A or Case B. It changes nothing. `delete-suspended` is the only cluster write: it deletes a HelmRelease
only when it is suspended, so helm-controller does not uninstall the release.

The git steps (prune guard, suspend, remove the old HelmRelease, add the HelmApp) stay manual: the tool does not
know the git source of the HelmRelease.
"""

import argparse
import json
import subprocess
import sys

import yaml

DEFAULT_REPOSITORY = "oci://gsoci.azurecr.io/charts/giantswarm"
MC_METADATA = ("flux-giantswarm", "management-cluster-metadata")
KUSTOMIZE_PRUNE = "kustomize.toolkit.fluxcd.io/prune"
OPERATOR_PRUNE = "fluxcd.controlplane.io/prune"

# HelmRelease spec fields that the HelmApp maps. All other fields are reported (WARN_FIELDS) or stop the move.
MAPPED_FIELDS = {"chartRef", "releaseName", "serviceAccountName", "kubeConfig", "targetNamespace",
                 "storageNamespace", "values", "valuesFrom", "dependsOn", "suspend"}
# The HelmApp sets its own value (or none) for these. The move changes them, but not the rendered chart.
WARN_FIELDS = {"interval", "timeout", "install", "upgrade", "rollback", "uninstall", "test", "driftDetection",
               "maxHistory", "persistentClient"}


class Stop(Exception):
    """A precondition of docs/migration.md fails: do not migrate."""


def wrap(hr, ocirepo, app, mc_name=None):
    """Return (helmapp, case, warnings) for a HelmRelease and its OCIRepository. Raise Stop on a stop condition."""
    meta, spec = hr["metadata"], hr["spec"]
    ns, hr_name = meta["namespace"], meta["name"]
    warnings = []

    other = sorted(set(spec) - MAPPED_FIELDS - WARN_FIELDS)
    if other:
        raise Stop(f"spec fields the HelmApp does not support: {', '.join(other)}")
    changed = sorted(set(spec) & WARN_FIELDS)
    if changed:
        warnings.append(f"these fields change to the HelmApp defaults: {', '.join(changed)}")

    ref = spec.get("chartRef")
    if not ref or ref.get("kind") != "OCIRepository":
        raise Stop("the chart is not from an OCIRepository (spec.chartRef)")
    if ref.get("namespace", ns) != ns:
        raise Stop("the OCIRepository is in another namespace")
    url = ocirepo["spec"]["url"]
    repository, _, chart_name = url.rstrip("/").rpartition("/")
    chart = {"name": chart_name}
    if repository != DEFAULT_REPOSITORY:
        chart["repository"] = repository
    chart["version"] = _deployed_version(hr, ocirepo)
    if ocirepo["spec"].get("secretRef"):
        chart["secretRef"] = {"name": ocirepo["spec"]["secretRef"]["name"]}

    target_ns = spec.get("targetNamespace", ns)
    storage_ns = spec.get("storageNamespace", ns)
    kubeconfig = (spec.get("kubeConfig") or {}).get("secretRef", {}).get("name")
    if kubeconfig:
        if not kubeconfig.endswith("-kubeconfig") or kubeconfig == "-kubeconfig":
            raise Stop(f"kubeConfig Secret {kubeconfig} is not named <cluster>-kubeconfig")
        cluster = kubeconfig[: -len("-kubeconfig")]
        if target_ns != storage_ns:
            raise Stop(f"targetNamespace {target_ns} differs from storageNamespace {storage_ns}")
        target = {"cluster": cluster}
        namespace = target_ns
    else:
        if not mc_name:
            raise Stop("an in-cluster HelmRelease needs the MC name (ConfigMap flux-giantswarm/management-cluster-metadata)")
        if target_ns != ns or storage_ns != ns:
            raise Stop(f"in-cluster targetNamespace/storageNamespace must be {ns}")
        cluster = mc_name
        target = {"inCluster": True}
        namespace = ns

    out = {"chart": chart, "namespace": namespace, "targets": {"static": [target]}}

    overrides = {}
    release = spec.get("releaseName") or _flux_default_release_name(hr_name, spec.get("targetNamespace"))
    if release != app:
        overrides["releaseName"] = release
    if spec.get("serviceAccountName"):
        overrides["serviceAccountName"] = spec["serviceAccountName"]
    if overrides:
        out["helmReleaseOverrides"] = overrides

    if spec.get("values"):
        out["values"] = spec["values"]
    values_from = list(spec.get("valuesFrom") or [])
    if any(v.get("targetPath") for v in values_from):
        raise Stop("valuesFrom with targetPath is not supported")
    if kubeconfig:
        values_from = _strip_derived_layers(values_from, cluster, app, warnings)
    if values_from:
        out["valuesFrom"] = values_from

    deps = spec.get("dependsOn") or []
    if any(d.get("namespace", ns) != ns for d in deps):
        raise Stop("dependsOn on a HelmRelease in another namespace is not supported")
    if deps:
        out["dependsOn"] = {"static": [d["name"] for d in deps]}

    if spec.get("suspend"):
        warnings.append("the HelmRelease is suspended; the HelmApp is not (Case B suspends the old one on purpose)")
    # Protect during the move, so a rollback removes the HelmApp without an uninstall (docs/migration.md, section 2).
    out["protect"] = True

    helmapp = {"apiVersion": "apps.giantswarm.io/v1alpha1", "kind": "HelmApp",
               "metadata": {"name": app, "namespace": ns}, "spec": out}
    case = "A" if hr_name == f"{cluster}-{app}" else "B"
    return helmapp, case, warnings


def _deployed_version(hr, ocirepo):
    history = (hr.get("status") or {}).get("history") or []
    if history and history[0].get("chartVersion"):
        return history[0]["chartVersion"]
    tag = ocirepo["spec"].get("ref", {}).get("tag")
    if not tag:
        raise Stop("no deployed chart version in status.history and no spec.ref.tag on the OCIRepository")
    return tag


def _flux_default_release_name(name, target_ns):
    # helm-controller default: '[targetNamespace-]name', shortened with a hash above 53 characters.
    release = f"{target_ns}-{name}" if target_ns else name
    if len(release) > 53:
        raise Stop("the default release name is longer than 53 characters (Flux shortens it); set spec.releaseName first")
    return release


def _strip_derived_layers(values_from, cluster, app, warnings):
    """Remove the layers the HelmApp adds by itself for a remote target, and report an order change."""
    first = {("ConfigMap", f"{cluster}-cluster-values")}
    last = {("ConfigMap", f"{cluster}-{app}-user-values"), ("Secret", f"{cluster}-{app}-user-values")}
    key = lambda v: (v["kind"], v["name"])
    kept = [v for v in values_from if key(v) not in first | last]
    derived = [v for v in values_from if key(v) in first | last]
    rendered = [v for v in derived if key(v) in first] + kept + [v for v in derived if key(v) in last]
    if [key(v) for v in rendered] != [key(v) for v in values_from]:
        warnings.append("the valuesFrom order changes: the HelmApp puts <cluster>-cluster-values first and the "
                        "user-values last; check the merged values")
    if any(v.get("valuesKey") not in (None, "values") for v in derived):
        warnings.append("a removed valuesFrom layer has a custom valuesKey; the HelmApp uses the default key")
    return kept


def steps(case, ns, hr_name, app, cluster):
    new = f"{cluster}-{app}"
    if case == "A":
        return [
            f"WRITE (git): add {KUSTOMIZE_PRUNE}: disabled to HelmRelease {ns}/{hr_name}; let the Kustomization apply it",
            f"READ: helmapp-wrap plan checks the annotation again; it must be on the live object",
            f"WRITE (git): remove HelmRelease {ns}/{hr_name} from git",
            f"READ: HelmRelease {ns}/{hr_name} is still there and Ready=True",
            f"WRITE (git): add the HelmApp {ns}/{app}",
            "READ: the HelmApp is Ready=True, the HelmRelease has the ResourceSet labels, helm history has no uninstall",
        ]
    return [
        f"WRITE (git): add {KUSTOMIZE_PRUNE}: disabled and spec.suspend: true to HelmRelease {ns}/{hr_name}",
        f"READ: .spec.suspend is true and the annotation is on the live object",
        f"WRITE: helmapp-wrap delete-suspended -n {ns} {hr_name} --yes (refuses when it is not suspended)",
        f"WRITE (git): remove HelmRelease {ns}/{hr_name} from git",
        "READ: the Helm release secrets are still there and helm history has the same last revision",
        f"WRITE (git): add the HelmApp {ns}/{app}",
        f"READ: HelmRelease {ns}/{new} runs one upgrade, helm history has no uninstall, the HelmApp is Ready=True",
    ]


def check_deletable(hr):
    """Raise Stop unless deleting the HelmRelease leaves the Helm release in place."""
    meta = hr["metadata"]
    if hr["spec"].get("suspend") is not True:
        raise Stop(f"HelmRelease {meta['namespace']}/{meta['name']} is not suspended: a delete uninstalls the release")
    if meta.get("deletionTimestamp"):
        raise Stop("the HelmRelease is already being deleted")
    annotations = meta.get("annotations") or {}
    if "disabled" not in (annotations.get(KUSTOMIZE_PRUNE), annotations.get(OPERATOR_PRUNE)):
        raise Stop(f"no {KUSTOMIZE_PRUNE}: disabled (or {OPERATOR_PRUNE}: disabled) annotation: "
                   "the owner can re-create or prune the object")


def kubectl(context, *args):
    out = subprocess.run(["kubectl", "--context", context, *args], check=True, capture_output=True, text=True)
    return out.stdout


def get(context, kind, ns, name):
    return json.loads(kubectl(context, "-n", ns, "get", kind, name, "-o", "json"))


def cmd_plan(a):
    hr = get(a.context, "helmrelease.helm.toolkit.fluxcd.io", a.namespace, a.name)
    ref = hr["spec"].get("chartRef") or {}
    if ref.get("kind") != "OCIRepository":
        raise Stop("the chart is not from an OCIRepository (spec.chartRef)")
    ocirepo = get(a.context, "ocirepository.source.toolkit.fluxcd.io", ref.get("namespace", a.namespace), ref["name"])
    mc_name = None
    if not hr["spec"].get("kubeConfig"):
        mc_name = get(a.context, "configmap", *MC_METADATA)["data"]["NAME"]
    helmapp, case, warnings = wrap(hr, ocirepo, a.app, mc_name)
    target = helmapp["spec"]["targets"]["static"][0]
    cluster = target.get("cluster", mc_name)
    manifest = yaml.safe_dump(helmapp, sort_keys=False)
    if a.output:
        with open(a.output, "w") as f:
            f.write(manifest)
    else:
        sys.stdout.write(manifest)
    err = sys.stderr
    print(f"Case {case}: HelmRelease {a.namespace}/{a.name} -> HelmApp {a.namespace}/{a.app} "
          f"(new HelmRelease {cluster}-{a.app})", file=err)
    for w in warnings:
        print(f"warning: {w}", file=err)
    annotations = hr["metadata"].get("annotations") or {}
    print(f"live: suspend={hr['spec'].get('suspend', False)} {KUSTOMIZE_PRUNE}={annotations.get(KUSTOMIZE_PRUNE)}",
          file=err)
    for i, s in enumerate(steps(case, a.namespace, a.name, a.app, cluster), 1):
        print(f"{i}. {s}", file=err)


def cmd_delete_suspended(a):
    hr = get(a.context, "helmrelease.helm.toolkit.fluxcd.io", a.namespace, a.name)
    check_deletable(hr)
    cmd = ["-n", a.namespace, "delete", "helmrelease.helm.toolkit.fluxcd.io", a.name]
    if not a.yes:
        print("dry run, would run: kubectl --context", a.context, *cmd)
        return
    print(kubectl(a.context, *cmd), end="")


def main(argv=None):
    p = argparse.ArgumentParser(prog="helmapp-wrap", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "delete-suspended"):
        s = sub.add_parser(name)
        s.add_argument("--context", required=True, help="kube context of the management cluster")
        s.add_argument("-n", "--namespace", required=True)
        s.add_argument("name", help="the HelmRelease name")
    sub.choices["plan"].add_argument("--app", required=True, help="the HelmApp name")
    sub.choices["plan"].add_argument("-o", "--output", help="write the HelmApp here, default stdout")
    sub.choices["delete-suspended"].add_argument("--yes", action="store_true", help="delete; default is a dry run")
    a = p.parse_args(argv)
    try:
        {"plan": cmd_plan, "delete-suspended": cmd_delete_suspended}[a.cmd](a)
    except Stop as e:
        print(f"stop: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(e.stderr, file=sys.stderr, end="")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
