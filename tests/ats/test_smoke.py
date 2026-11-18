"""ATS smoke for the crossplane-app-platform chart.

app-test-suite (ATS >= 1.0) installs the packaged chart on the job's kind
cluster with `helm upgrade --install --wait` (the namespace from
.ats/main.yaml) and runs this file with `pytest -m smoke`: the generated
execute-chart-tests job of every branch build. ATS applies the Crossplane
CRDs in tests/ats/crds first (`cluster-crds` in .ats/main.yaml), as the chart
renders an XRD and a Composition. No Crossplane runs on the kind cluster, so
the smoke checks that the cluster is reachable and the HelmApp XRD exists (the
Composition is not checked), not that they work. Mark the checks
that must hold across a chart upgrade with
@pytest.mark.upgrade once .ats/main.yaml runs the upgrade scenario. The
dependencies are the generated tests/ats/pyproject.toml, owned by
giantswarm/devctl; this file and .ats/main.yaml are the repository's own.
"""

import pykube
import pytest
from pykube.objects import APIObject
from pytest_helm_charts.clusters import Cluster


class CompositeResourceDefinition(APIObject):
    version = "apiextensions.crossplane.io/v2"
    endpoint = "compositeresourcedefinitions"
    kind = "CompositeResourceDefinition"


@pytest.mark.smoke
def test_api_working(kube_cluster: Cluster) -> None:
    """The kind cluster ATS runs against is reachable."""
    assert kube_cluster.kube_client is not None
    assert len(pykube.Node.objects(kube_cluster.kube_client)) >= 1


@pytest.mark.smoke
def test_helmapp_xrd_installed(kube_cluster: Cluster) -> None:
    """The chart installed the HelmApp XRD. No Crossplane runs here, so it is not established."""
    xrd = CompositeResourceDefinition.objects(kube_cluster.kube_client).get(name="helmapps.apps.giantswarm.io")
    assert xrd.obj["spec"]["scope"] == "Namespaced"
