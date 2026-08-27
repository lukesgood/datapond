"""The Namespace must never be a Helm hook.

Written after it was, and after that cost a live outage on 2026-08-27.

A hook resource is not part of the release manifest. Making the Namespace one on an
existing deployment means the next `helm upgrade` sees a resource that has left the
manifest and deletes it — and with the namespace go the pods, the secrets, the TLS
certificate, and the release history itself, which Helm 3 stores as secrets *inside
that namespace*. There is no rollback afterwards, because rollback needs the history.

The fresh-install ordering that motivated the hook — a pre-install Job needs somewhere
to run — is Helm's own `--create-namespace`, which runs before any hook. That belongs
in the install command, not in a manifest resource that upgrades then reinterpret.
"""
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "helm/datapond/templates"


def test_the_namespace_is_an_ordinary_resource():
    body = (TEMPLATES / "namespace.yaml").read_text()
    assert "helm.sh/hook" not in body, (
        "The Namespace is a Helm hook again. On any existing deployment the next "
        "upgrade will delete it — see this file's docstring."
    )


def test_no_template_that_declares_a_namespace_is_a_hook():
    """The rule is about the resource, not the filename someone puts it in."""
    for path in sorted(TEMPLATES.glob("*.yaml")):
        body = path.read_text()
        if "kind: Namespace" not in body:
            continue
        assert "helm.sh/hook" not in body, f"{path.name} makes a Namespace a hook"


def test_the_fresh_install_path_creates_the_namespace_itself():
    """Reverting the hook re-opens the ordering it was written for, so the install
    command has to carry the fix instead. Without this the ephemeral job fails again
    with `namespaces "datapond" not found`, which is how the hook got written."""
    ci = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
    install = ci.split("Install from nothing", 1)
    assert len(install) == 2, "the fresh-install step was renamed"
    step = install[1].split("- name:", 1)[0]
    assert "--create-namespace" in step
    assert "--namespace datapond" in step


def test_the_chart_does_not_also_render_a_namespace_on_that_path():
    """`--create-namespace` makes the namespace without Helm ownership metadata, so a
    chart-rendered Namespace on top of it collides. The ephemeral profile has to turn
    the chart's own off — which is also what keeps a Namespace out of the manifest,
    and therefore out of reach of a future upgrade's delete."""
    values = (Path(__file__).resolve().parents[2]
              / "helm/datapond/values-ephemeral.yaml").read_text()
    assert "createNamespace: false" in values
