"""Which of the eight optional OSS add-ons a chart render includes, and why.

The base `values.yaml` used to set all eight to `enabled: true`. A deployment that
picked no profile therefore got the wide platform, and `values-aws.yaml` — which states
none of the eight — inherited exactly that. Flipping the default to `false` would narrow
new installs but silently delete the add-on from any existing deployment that never
chose, on its next upgrade: Helm cannot tell an explicit `false` from a defaulted one,
so a boolean default cannot express "leave what is already running alone."

`enabled` is three-state instead: `true` runs it, `false` removes it, and *unset* (the
new default) means "keep it if this namespace is already running it, otherwise off" —
resolved by `templates/_addons.tpl`'s `datapond.addonEnabledOrPreserved`, the same
explicit -> existing -> generated shape `templates/secrets.yaml` already uses for
passwords. `helm template` never has a cluster, so its `lookup` always comes back empty
and every offline render takes the "off" branch — which is exactly the lean default this
file pins. The "existing and preserved" branch needs a real cluster; that is C4's job in
CI, not this file's.

The helper takes `kind` explicitly, with no default, at every call site. The obvious
alternative — defaulting `kind` to "Deployment" — was tried against the eight real
templates first: `spark-statefulset.yaml` creates no Deployment at all, only two
StatefulSets (`spark-master`, `spark-worker`). A defaulted "Deployment" lookup for spark
would never find the running StatefulSet, "unset" would always resolve to "off", and an
existing install running Spark by default would lose it on the very first upgrade to
this chart version — silently, since `helm template` cannot reveal it (no cluster) and
the render looks identical either way in review. Requiring `kind` at every call site is
what stops the next StatefulSet-shaped add-on from inheriting the same bug quietly.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm/datapond"
VALUES = CHART / "values.yaml"

# component -> (template file, kind of the one object that certainly exists whenever
# the component is on, suffix appended to `.Values.<component>.name` for that object's
# metadata.name -- or None when the object's name is the bare `.Values.<component>.name`
# with no suffix). Chosen to be a resource each template renders unconditionally (behind
# only the component's own top-level enabled guard, not behind a second flag), per the
# controller's ruling on C1's spark defect.
ADDONS = {
    "airflow": ("airflow-deployment.yaml", "Deployment", "webserver"),
    "spark": ("spark-statefulset.yaml", "StatefulSet", "master"),
    "polaris": ("polaris-deployment.yaml", "Deployment", None),
    "risingwave": ("risingwave-statefulset.yaml", "Deployment", "frontend"),
    "openmetadata": ("openmetadata-deployment.yaml", "Deployment", "server"),
    "jupyter": ("jupyter-deployment.yaml", "Deployment", None),
    "mlflow": ("mlflow-deployment.yaml", "Deployment", None),
    "trino": ("trino-deployment.yaml", "Deployment", None),
}


def helm_template(extra_args=()):
    """Shell out to `helm template`, the way the other test_helm_*.py files do for a
    static render, extended here with `--set` overrides since this file's whole point
    is what changes as `enabled` changes."""
    cmd = ["helm", "template", "datapond", str(CHART), "--namespace", "datapond", *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"helm template failed:\n{result.stderr}"
    return result.stdout


def rendered_names(rendered: str, kind: str) -> set:
    """Every metadata.name of a top-level object of `kind` in a rendered manifest."""
    return set(re.findall(rf"\nkind: {re.escape(kind)}\nmetadata:\n\s*name: (\S+)\n", rendered))


def default_name(component: str) -> str:
    """The default `.Values.<component>.name` from the base values.yaml, read fresh
    rather than hard-coded so this stays true if a default ever changes."""
    text = VALUES.read_text()
    m = re.search(rf"\n{component}:\n(?:  .*\n)*?  name: (\S+)\n", text)
    assert m, f"could not find `name:` under `{component}:` in values.yaml"
    return m.group(1)


def expected_name(component: str) -> str:
    _, _, suffix = ADDONS[component]
    base = default_name(component)
    return f"{base}-{suffix}" if suffix else base


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_explicit_true_renders_it(component):
    _, kind, _ = ADDONS[component]
    rendered = helm_template([f"--set={component}.enabled=true"])
    assert expected_name(component) in rendered_names(rendered, kind), (
        f"{component}: explicit enabled=true should render a {kind} named "
        f"{expected_name(component)!r}")


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_explicit_false_removes_it(component):
    _, kind, _ = ADDONS[component]
    rendered = helm_template([f"--set={component}.enabled=false"])
    assert expected_name(component) not in rendered_names(rendered, kind), (
        f"{component}: explicit enabled=false must remove it even if this namespace "
        f"is already running it -- that is the only way to turn one off")


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_unset_with_no_cluster_defaults_to_off(component):
    """`helm template` has no cluster, so an unset `enabled` (the base default) must
    resolve to off. This is the lean-default behaviour the whole task exists for."""
    _, kind, _ = ADDONS[component]
    rendered = helm_template([])
    assert expected_name(component) not in rendered_names(rendered, kind), (
        f"{component}: with `enabled` unset and no cluster to look up, this must not "
        f"render -- a base install that picks no profile should stay lean")


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_every_addon_template_routes_through_the_helper(component):
    """No template may read `.Values.<component>.enabled` directly any more -- that
    bare boolean read is exactly what cannot distinguish an explicit false from a
    defaulted one."""
    template_file, _, _ = ADDONS[component]
    text = (CHART / "templates" / template_file).read_text()
    assert 'include "datapond.addonEnabledOrPreserved"' in text, (
        f"{template_file} must route its guard through the shared helper")
    assert f".Values.{component}.enabled" not in text, (
        f"{template_file} still reads .Values.{component}.enabled directly -- that "
        f"bypasses the three-state resolution entirely")


GUARD_RE = re.compile(
    r'\{\{-\s*if eq "true" \(include "datapond\.addonEnabledOrPreserved" \(dict "root" \$ '
    r'"component" "(?P<component>\w+)" "kind" "(?P<kind>\w+)" '
    r'"name" (?P<name_expr>.+?)\)\)\s*\}\}'
)

# A resource's own `metadata.name:` field, e.g. `{{ .Values.airflow.name }}-webserver`
# or the bare `{{ .Values.polaris.name }}`.
RESOURCE_NAME_RE = re.compile(
    r'\nkind: (?P<kind>\w+)\nmetadata:\n\s*name: \{\{ \.Values\.(?P<component>\w+)\.name \}\}(?P<suffix>-[\w-]+)?\n'
)


def _normalize_guard_name_expr(expr: str):
    """Reduce a guard's `name` argument to (component, suffix) so it can be compared
    against a resource's own metadata.name regardless of Go-template idiom -- a bare
    `$.Values.x.name` for a suffix-less name, or `(printf "%s-suffix" $.Values.x.name)`
    for a suffixed one (dict values can't nest a second `{{ }}` action, so a suffixed
    name can't be written as the bare interpolation form the resource itself uses)."""
    bare = re.fullmatch(r'\$\.Values\.(\w+)\.name', expr)
    if bare:
        return bare.group(1), None
    printf = re.fullmatch(r'\(printf "%s-([\w-]+)" \$\.Values\.(\w+)\.name\)', expr)
    if printf:
        return printf.group(2), printf.group(1)
    return None, None


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_the_kind_and_name_passed_to_the_helper_match_a_rendered_object(component):
    """The most important test in this file. A preserve rule that looks for the wrong
    object silently never preserves: it would look correct in review, render correctly
    offline, and quietly delete workloads on a real upgrade. This asserts the (kind,
    name) the guard passes to the helper is exactly the (kind, name) of an object the
    same template actually renders -- not merely that some Deployment exists somewhere
    in the file."""
    template_file, expected_kind, expected_suffix = ADDONS[component]
    text = (CHART / "templates" / template_file).read_text()

    guard = GUARD_RE.search(text)
    assert guard, f"{template_file}: no addonEnabledOrPreserved guard found"
    assert guard.group("component") == component
    assert guard.group("kind") == expected_kind, (
        f"{template_file}: guard passes kind={guard.group('kind')!r} but the object "
        f"this component certainly renders is a {expected_kind}")

    guard_component, guard_suffix = _normalize_guard_name_expr(guard.group("name_expr"))
    assert (guard_component, guard_suffix) == (component, expected_suffix), (
        f"{template_file}: guard's name expression {guard.group('name_expr')!r} does "
        f"not resolve to .Values.{component}.name"
        + (f" + {expected_suffix!r}" if expected_suffix else " with no suffix"))

    rendered_resources = {
        (m.group("kind"), m.group("component"), m.group("suffix"))
        for m in RESOURCE_NAME_RE.finditer(text)
    }
    assert (expected_kind, component, (f"-{expected_suffix}" if expected_suffix else None)) in rendered_resources, (
        f"{template_file}: no {expected_kind} named "
        f"{{{{ .Values.{component}.name }}}}"
        + (f"-{expected_suffix}" if expected_suffix else "")
        + " actually appears in this template -- the guard's (kind, name) does not "
          "match anything the template renders")


# ---------------------------------------------------------------------------
# C2 — NOTES.txt reports what the three-state resolution resolved to.
#
# `helm template` does not render NOTES.txt (only `helm install`/`upgrade` do), so this
# asserts on the file's own content: it must name every one of the eight add-ons, the
# one-line `--set <component>.enabled=false` that turns each off, and the word
# "preserved" -- an operator reading the install output needs to see all eight, not a
# subset. A NOTES.txt that lists only some add-ons is worse than none: the operator
# would conclude the rest are off when an unset one may in fact have been preserved.
# ---------------------------------------------------------------------------

NOTES = CHART / "templates" / "NOTES.txt"


def test_notes_file_exists():
    assert NOTES.exists(), "helm/datapond/templates/NOTES.txt must exist"


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_notes_names_every_addon(component):
    text = NOTES.read_text()
    assert component in text, (
        f"NOTES.txt does not mention {component!r} -- a NOTES.txt that lists only "
        f"some add-ons is worse than none, since the operator concludes the rest "
        f"are off")


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_notes_gives_the_off_switch_for_every_addon(component):
    text = NOTES.read_text()
    assert f"--set {component}.enabled=false" in text, (
        f"NOTES.txt does not give the one-line --set to turn {component!r} off")


def test_notes_explains_preservation():
    text = NOTES.read_text()
    assert "preserved" in text, (
        "NOTES.txt must say which add-ons were kept because they were already "
        "running -- that is the whole point of the three-state default")


# ---------------------------------------------------------------------------
# C3 — which add-ons a profile renders, as an assertion.
#
# No test asserted this before this file: the helm-lint CI job renders these profiles
# and checks only that each renders without error, and the other test_helm_*.py files
# pin security contexts, storage classes, duplicate keys and ordering -- never a
# workload list. So a change to the base defaults (the previous commit) had nothing to
# update and nothing that would have caught it going wrong. This is that check.
#
# Expected sets verified directly against `helm template` output for each profile
# before being written here (not assumed from the profile files' prose):
#   - base values.yaml, values-foundation.yaml, values-prod-single.yaml and
#     values-aws.yaml all render none of the eight -- base and values-aws.yaml are the
#     two that move relative to before the previous commit (base used to enable all
#     eight; values-aws.yaml states none of the eight itself and inherited base's all-
#     true default). That movement is the measurement of what the defaults change did,
#     not a defect to fix here.
#   - values-onprem.yaml renders all eight (explicit true throughout, per
#     values-onprem.yaml's own full-OSS-stack intent).
#   - values-quicktest.yaml renders seven of eight -- every add-on except spark, which
#     it explicitly sets to false.
#   - values-dev.yaml renders exactly what it states: airflow, spark, jupyter, mlflow,
#     openmetadata and risingwave true; polaris and trino left unset (so, with no
#     cluster, off).
# ---------------------------------------------------------------------------

ALL_ADDONS = frozenset(ADDONS)

PROFILE_EXPECTATIONS = {
    None: frozenset(),  # base values.yaml, no --values override
    "values-foundation.yaml": frozenset(),
    "values-prod-single.yaml": frozenset(),
    "values-aws.yaml": frozenset(),
    "values-onprem.yaml": ALL_ADDONS,
    "values-quicktest.yaml": ALL_ADDONS - {"spark"},
    "values-dev.yaml": frozenset(
        {"airflow", "spark", "jupyter", "mlflow", "openmetadata", "risingwave"}),
}


@pytest.mark.parametrize("profile", sorted(PROFILE_EXPECTATIONS, key=lambda p: p or ""))
def test_profile_renders_exactly_its_expected_addons(profile):
    expected = PROFILE_EXPECTATIONS[profile]
    args = [f"--values={CHART / profile}"] if profile else []
    rendered = helm_template(args)

    present = set()
    for component in ALL_ADDONS:
        _, kind, _ = ADDONS[component]
        if expected_name(component) in rendered_names(rendered, kind):
            present.add(component)

    label = profile or "values.yaml (base)"
    assert present == expected, (
        f"{label}: rendered add-ons {sorted(present)} != expected {sorted(expected)}")
