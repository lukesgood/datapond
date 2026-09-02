"""Which of the eight optional OSS add-ons a chart render includes, and why.

The base `values.yaml` used to set all eight to `enabled: true`. A deployment that
picked no profile therefore got the wide platform, and `values-aws.yaml` — which states
none of the eight — inherited exactly that. Flipping the default to `false` would narrow
new installs but silently delete the add-on from any existing deployment that never
chose, on its next upgrade: Helm cannot tell an explicit `false` from a defaulted one,
so a boolean default cannot express "leave what is already running alone."

`enabled` is three-state instead: `true` runs it, `false` removes it, and *unset* (the
new default) means "keep it if this namespace is already running it, otherwise off" —
resolved by `templates/_addons.tpl`, the same explicit -> existing -> generated shape
`templates/secrets.yaml` already uses for passwords. `helm template` never has a cluster,
so its `lookup` always comes back empty and every offline render takes the "off" branch —
which is exactly the lean default this file pins. The "existing and preserved" branch
needs a real cluster; that is CI's job, not this file's.

WHY THE SCAN BELOW COVERS EVERY TEMPLATE, NOT JUST THE EIGHT WORKLOADS. The first
version of this file scanned only the eight add-on workload templates, and that omission
is what let two blockers through review. An unset flag is `null`, and `null` is falsy to
every two-state reader, so:

  * `backend-deployment.yaml` emitted `value: "{{ dig "enabled" true .Values.trino }}"`.
    Helm drops a null-valued key while coalescing, so `dig` never saw `enabled` and
    returned its `true` default — the backend was told all eight add-ons were on while
    the chart rendered none of them. The same `dig` shape guarded the backend pod's
    own `airflow-dags-pvc` mount, so a lean base install rendered a backend that
    claimed a PVC nothing created: the core service could not schedule at all. That
    one was found by this scan and not by the review that prompted it.
  * Twelve more templates read `.Values.<component>.enabled` directly and resolved an
    unset flag to off *while the workload itself was preserved*. A preserved airflow lost
    AIRFLOW_PASSWORD; a preserved spark lost the spark-defaults Secret it mounts; every
    preserved add-on lost its ingress path; trino and polaris lost iceberg-warehouse-pvc
    while trino-deployment.yaml still claimed it, i.e. data loss.

Neither is visible in a render diff of the eight workloads, which is precisely why the
scan now covers the whole templates/ directory: no template outside `_addons.tpl` may
read one of the eight flags at all.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "helm/datapond"
VALUES = CHART / "values.yaml"
TEMPLATES = CHART / "templates"
ADDONS_TPL = TEMPLATES / "_addons.tpl"

# component -> (template file, kind of the one object that certainly exists whenever
# the component is on, suffix appended to `.Values.<component>.name` for that object's
# metadata.name -- or None when the object's name is the bare `.Values.<component>.name`
# with no suffix). Chosen to be a resource each template renders unconditionally (behind
# only the component's own top-level enabled guard, not behind a second flag).
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


# ---------------------------------------------------------------------------
# The scan: nothing outside _addons.tpl may read one of the eight flags.
# ---------------------------------------------------------------------------

# `_addons.tpl` is the one file allowed to resolve an add-on flag; it reads `enabled`
# via `index ... "enabled"` and describes the two-state readings it replaced in prose,
# so a textual scan of it would only ever match its own documentation.
SCAN_EXEMPT = {"_addons.tpl"}

# Every way a template can ask the question, all of them routed through the one
# resolution point in _addons.tpl.
HELPERS = ('include "datapond.addonOn"', 'include "datapond.addonEnabledOrPreserved"')

# The scan used to name two spellings: `.Values.trino.enabled` and the exact string
# `dig "enabled" true .Values.trino`. Both were the shapes that had already gone wrong,
# and a scan that only knows the shapes it has already seen catches the bug it was
# written for and nothing else. `dig "enabled" true (.Values.trino | default dict)` is
# the same defaulting read with parentheses around the dict, backend-deployment.yaml
# uses that exact form six times for other components, and it was invisible to both
# patterns — so the next add-on env var, copied from the six neighbours, would have
# reintroduced the bug the scan exists to stop.
#
# So the scan asks the question structurally instead: inside one template action, does
# this template both name one of the eight in a Values path and read an `enabled` key?
# The shape between them — dig, index, pluck, get, a dict literal, a bare attribute —
# does not matter, which is the point. Two things follow: what counts as "names a
# component" and "reads enabled" is written once, and the corpus in
# test_the_scan_sees_every_shape_this_class_has_taken pins what the detector actually
# catches, so a narrowing is a failing test rather than a silence.

# One template action. Comment actions are dropped first: they do not render, so prose
# quoting a forbidden shape is documentation, not a second implementation.
ACTION_RE = re.compile(r"\{\{(?!/\*).*?\}\}", re.S)
COMMENT_ACTION_RE = re.compile(r"\{\{/\*.*?\*/\}\}", re.S)

_COMPONENTS = "|".join(sorted(ADDONS))

# The component's OWN flag, as an attribute path. The path has to end at `enabled` with
# nothing in between: `.Values.airflow.persistence.enabled` and `.Values.trino.rls.enabled`
# are two-state sub-options of a component, not the three-state flag, and they stay legal.
OWN_ATTRIBUTE_RE = re.compile(
    r"(?:Values|\$v)\.(?P<component>%s)\.enabled\b" % _COMPONENTS)

# The same flag read as a quoted key -- dig, index, pluck, get -- in any arrangement.
# Two halves: the key appears as a string somewhere in the action, and the component
# sits at the END of a Values path (`.Values.trino`, `($.Values.trino | default dict)`,
# `index .Values "trino"`). Ending there is again what separates the component's own
# flag from a sub-option; a path that continues is reading something else.
#
# The cost of not parsing: an action that reads some *other* key by string out of a
# component's own dict trips this too. Nothing in the chart does that today, and the fix
# if something ever needs to is to spell that read as an attribute path.
QUOTED_KEY_RE = re.compile(r'"enabled"')
COMPONENT_PATH_END_RE = re.compile(
    r'(?:Values|\$v)\s*(?:\.(?P<attr>%s)|\[?\s*"(?P<key>%s)")(?![\w."])'
    % (_COMPONENTS, _COMPONENTS))

# A Values subtree chosen by a variable, so the read names no component at all. The only
# reason to reach into Values dynamically in this chart is to walk the eight, which is
# `_addons.tpl`'s job -- NOTES.txt did exactly this and held a second copy of the rule
# that no name-based scan could ever see.
DYNAMIC_VALUES_RE = re.compile(r"Values\s*\[?\s*\$\w+")


def actions(text: str):
    return ACTION_RE.findall(COMMENT_ACTION_RE.sub("", text))


def addon_flag_reads(text: str):
    """Every place `text` resolves one of the eight `enabled` flags itself.

    Returns (component, action) pairs, `component` being None for a read that selects
    its component through a variable and so names none."""
    found = []
    for action in actions(text):
        quoted = QUOTED_KEY_RE.search(action)
        named = {m.group("component") for m in OWN_ATTRIBUTE_RE.finditer(action)}
        if quoted:
            named |= {m.group("attr") or m.group("key")
                      for m in COMPONENT_PATH_END_RE.finditer(action)}
        found.extend((component, action) for component in sorted(named))
        if not named and quoted and DYNAMIC_VALUES_RE.search(action):
            found.append((None, action))
    return found


def scanned_templates():
    return sorted(p for p in TEMPLATES.iterdir()
                  if p.is_file() and p.name not in SCAN_EXEMPT)


@pytest.mark.parametrize("template", scanned_templates(), ids=lambda p: p.name)
def test_no_template_resolves_an_addon_flag_itself(template):
    """The check whose absence is why two blockers reached final review. `enabled` is
    three-state; every two-state read sees an unset flag as off, so it deletes the
    ingress path, ServiceAccount, secret key, database or PVC out from under a workload
    the guard preserved. A `dig` default is the subtler half — Helm drops a null-valued
    key while coalescing, so `dig` never finds `enabled` and hands back its own default,
    which is how the backend came to be told all eight add-ons were on while the chart
    rendered none of them."""
    named = sorted({c for c, _ in addon_flag_reads(template.read_text()) if c})
    assert not named, (
        f"{template.name} resolves the enabled flag of {', '.join(named)} itself. "
        f"Whatever the shape -- attribute, dig with a default, index, pluck -- an unset "
        f"flag reads as off (or as the default), not as the three-state answer, so this "
        f"renders OFF for an add-on the workload guard preserved as ON. Ask "
        f"`include \"datapond.addonOn\" (dict \"root\" $ \"component\" \"{named[0]}\")` "
        f"instead, or `datapond.addonEnabledOrPreserved` for a value.")


@pytest.mark.parametrize("template", scanned_templates(), ids=lambda p: p.name)
def test_no_template_reads_the_enabled_key_dynamically(template):
    """The shape a name-based scan cannot see: reaching into `.Values` by variable and
    pulling `"enabled"` out of whatever comes back. It names no component, so it walks
    all eight at once -- a second implementation of the rule, in a file that is not
    `_addons.tpl`. NOTES.txt held exactly this."""
    dynamic = [a for c, a in addon_flag_reads(template.read_text()) if c is None]
    assert not dynamic, (
        f"{template.name} reads the enabled key out of a Values subtree chosen by a "
        f"variable:\n  {dynamic[0].strip()}\n"
        f"That is a second copy of the three-state rule. Ask `datapond.addonState` for "
        f"the reason and `datapond.addonEnabledOrPreserved` for the answer.")


# Positives are the shapes this bug has actually taken, plus the ones a person would
# write next; negatives are the reads in this chart today that must stay legal. The two
# lists are the scan's coverage, stated where it can fail rather than assumed.
SHAPES_THAT_MUST_BE_CAUGHT = [
    ("bare attribute", "{{- if .Values.trino.enabled }}"),
    ("attribute in a dict literal", '{{- $x := (dict "enabled" .Values.spark.enabled) }}'),
    ("dig with a default", '{{ dig "enabled" true .Values.trino }}'),
    ("dig, parenthesised dict", '{{ dig "enabled" true (.Values.trino | default dict) }}'),
    ("dig, root-scoped", '{{ dig "enabled" false ($.Values.spark | default dict) }}'),
    ("index with literal keys", '{{- $x := index .Values "airflow" "enabled" }}'),
    ("index, nested and defaulted",
     '{{- $x := index ((index $.Values "mlflow") | default dict) "enabled" }}'),
    ("pluck", '{{ pluck "enabled" .Values.jupyter | first }}'),
    ("get", '{{ get (.Values.polaris | default dict) "enabled" }}'),
    ("through a $v := .Values alias", "{{- $x := $v.openmetadata.enabled }}"),
    ("dynamic, naming no component",
     '{{- $e := index ((index $.Values $component) | default dict) "enabled" }}'),
]

SHAPES_THAT_MUST_STAY_LEGAL = [
    ("a non-add-on component, the form used six times in backend-deployment.yaml",
     '{{ dig "enabled" true (.Values.backend.ragScheduler | default dict) }}'),
    ("a non-add-on component, doubly defaulted",
     '{{ dig "enabled" false ((.Values.governance | default dict).rls | default dict) }}'),
    ("a plain two-state flag", "{{- if .Values.ingress.enabled }}"),
    ("the guard helper", '{{- if include "datapond.addonOn" (dict "root" $ "component" "trino") }}'),
    ("the value helper",
     '{{ include "datapond.addonEnabledOrPreserved" (dict "root" $ "component" "spark") }}'),
    ("a component named as a string beside an unrelated enabled key",
     '{{- include "datapond.serviceAccounts" (list (dict "name" "datapond-trino" "enabled" '
     '(include "datapond.addonOn" (dict "root" $ "component" "trino")))) }}'),
    ("prose in a template comment", '{{/* never write `dig "enabled" true .Values.trino` */}}'),
    # The distinction the first widening got wrong: these are two-state sub-options of
    # an add-on, not the add-on's own three-state flag, and all three are in the chart.
    ("a sub-option of an add-on", "{{- if .Values.trino.rls.enabled }}"),
    ("a second sub-option", "{{- if .Values.airflow.persistence.enabled }}"),
    ("a nested sub-option", "{{ .Values.openmetadata.pipelineServiceClient.enabled }}"),
]


@pytest.mark.parametrize("label,shape", SHAPES_THAT_MUST_BE_CAUGHT, ids=lambda v: v if isinstance(v, str) else "")
def test_the_scan_sees_every_shape_this_class_has_taken(label, shape):
    """A scan is only as good as the shapes it recognises, and the previous one
    recognised two. Each of these is a real way to resolve the flag outside
    `_addons.tpl`; a change that stops catching one narrows the scan back toward the
    blind spot that let the blockers through."""
    assert addon_flag_reads(shape), f"the scan no longer catches {label}: {shape}"


@pytest.mark.parametrize("label,shape", SHAPES_THAT_MUST_STAY_LEGAL, ids=lambda v: v if isinstance(v, str) else "")
def test_the_scan_leaves_the_legitimate_reads_alone(label, shape):
    """The other half of a widened scan: it must not start failing the chart's ordinary
    two-state flags. Every one of these is in the chart today."""
    assert not addon_flag_reads(shape), f"the scan wrongly flags {label}: {shape}"


def test_the_scan_covers_more_than_the_eight_workload_templates():
    """A scan that quietly shrinks back to the eight workload templates would restore
    exactly the blind spot this file exists to close. This pins that the scan is over
    the whole directory."""
    scanned = {p.name for p in scanned_templates()}
    workloads = {f for f, _, _ in ADDONS.values()}
    assert workloads <= scanned
    assert len(scanned) > len(workloads) + 10, (
        f"the scan covers only {len(scanned)} templates -- it must cover the whole "
        f"templates/ directory, not just the add-on workloads")


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_every_addon_workload_template_asks_the_helper(component):
    """The positive half: each add-on's own template must still route its top-level
    guard through the shared helper rather than through nothing at all."""
    template_file, _, _ = ADDONS[component]
    text = (TEMPLATES / template_file).read_text()
    assert any(h in text for h in HELPERS), (
        f"{template_file} must route its guard through the shared helper")


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_the_backend_is_told_the_same_answer_the_chart_rendered(component):
    """FEATURE_* drives /api/capabilities, which drives which surfaces the console
    advertises. If it disagrees with what rendered, the console offers pages over
    services that do not exist -- which is exactly what `dig "enabled" true` produced."""
    _, kind, _ = ADDONS[component]
    for args, expected in (([], "false"),
                           ([f"--set={component}.enabled=true"], "true"),
                           ([f"--set={component}.enabled=false"], "false")):
        rendered = helm_template(args)
        m = re.search(rf'- name: FEATURE_{component.upper()}\n\s*value: "?([a-z]+)"?',
                      rendered)
        assert m, f"FEATURE_{component.upper()} not found in the rendered backend env"
        assert m.group(1) == expected, (
            f"{component} with {args or 'no override'}: FEATURE_{component.upper()} is "
            f"{m.group(1)!r} but should be {expected!r}")
        workload_present = expected_name(component) in rendered_names(rendered, kind)
        assert workload_present == (expected == "true"), (
            f"{component} with {args or 'no override'}: FEATURE_"
            f"{component.upper()}={m.group(1)} but the {kind} "
            f"{'is missing' if expected == 'true' else 'rendered anyway'}")


# ---------------------------------------------------------------------------
# The one table, and whether its rows point at objects that exist.
# ---------------------------------------------------------------------------

def addon_target_row(component: str):
    """Parse one row of `datapond.addonTargets` — the single place the (component,
    kind, name) triples live now. Returns (kind, dig-default-name, suffix)."""
    text = ADDONS_TPL.read_text()
    suffixed = re.search(
        rf'set \$t "{component}"\s+\(dict "kind" "(\w+)"\s+"name" '
        rf'\(printf "%s-([\w-]+)"\s+\(dig "name" "([\w-]+)"', text)
    if suffixed:
        return suffixed.group(1), suffixed.group(3), suffixed.group(2)
    bare = re.search(
        rf'set \$t "{component}"\s+\(dict "kind" "(\w+)"\s+"name"\s+'
        rf'\(dig "name" "([\w-]+)"', text)
    assert bare, f"_addons.tpl has no addonTargets row for {component!r}"
    return bare.group(1), bare.group(2), None


RESOURCE_NAME_RE = re.compile(
    r'\nkind: (?P<kind>\w+)\nmetadata:\n\s*name: \{\{ \.Values\.(?P<component>\w+)\.name \}\}(?P<suffix>-[\w-]+)?\n'
)


@pytest.mark.parametrize("component", sorted(ADDONS))
def test_the_table_row_matches_an_object_its_template_renders(component):
    """The most important test in this file. A preserve rule that looks for the wrong
    object silently never preserves: it would look correct in review, render correctly
    offline, and quietly delete workloads on a real upgrade. This asserts the (kind,
    name) in `datapond.addonTargets` is exactly the (kind, name) of an object the
    component's own template renders -- not merely that some Deployment exists
    somewhere in the file."""
    template_file, expected_kind, expected_suffix = ADDONS[component]
    kind, dig_default, suffix = addon_target_row(component)

    assert kind == expected_kind, (
        f"_addons.tpl passes kind={kind!r} for {component} but the object it certainly "
        f"renders is a {expected_kind}")
    assert suffix == expected_suffix, (
        f"_addons.tpl builds {component}'s lookup name with suffix {suffix!r}, "
        f"expected {expected_suffix!r}")
    assert dig_default == default_name(component), (
        f"_addons.tpl falls back to {dig_default!r} when .Values.{component}.name is "
        f"absent, but values.yaml's default is {default_name(component)!r} -- the "
        f"lookup would search for an object that is never created")

    text = (TEMPLATES / template_file).read_text()
    rendered_resources = {
        (m.group("kind"), m.group("component"), m.group("suffix"))
        for m in RESOURCE_NAME_RE.finditer(text)
    }
    assert (expected_kind, component, (f"-{expected_suffix}" if expected_suffix else None)) in rendered_resources, (
        f"{template_file}: no {expected_kind} named "
        f"{{{{ .Values.{component}.name }}}}"
        + (f"-{expected_suffix}" if expected_suffix else "")
        + " actually appears in this template -- the table's (kind, name) does not "
          "match anything the template renders")


def test_the_table_holds_exactly_the_eight_addons():
    text = ADDONS_TPL.read_text()
    rows = set(re.findall(r'set \$t "(\w+)"', text))
    assert rows == set(ADDONS), (
        f"datapond.addonTargets holds {sorted(rows)}, expected {sorted(ADDONS)} -- a "
        f"missing row makes the helper fail loudly, an extra one is untested")


# ---------------------------------------------------------------------------
# NOTES.txt reports what the three-state resolution resolved to.
#
# `helm template` does not render NOTES.txt (only `helm install`/`upgrade` do), so this
# asserts on the file's own content: it must name every one of the eight add-ons, the
# one-line `--set <component>.enabled=false` that turns each off, and the word
# "preserved" -- an operator reading the install output needs to see all eight, not a
# subset. NOTES.txt derives both lists from `datapond.addonTargets`, so "names every
# add-on" is now a property of the table rather than of a hand-kept second copy.
# ---------------------------------------------------------------------------

NOTES = TEMPLATES / "NOTES.txt"


def test_notes_file_exists():
    assert NOTES.exists(), "helm/datapond/templates/NOTES.txt must exist"


def test_notes_derives_its_list_from_the_one_table():
    text = NOTES.read_text()
    assert 'include "datapond.addonTargets"' in text, (
        "NOTES.txt must range over datapond.addonTargets rather than hand-listing the "
        "eight add-ons -- a second copy of the list drifts from the first")
    assert ".enabled=false" in text, (
        "NOTES.txt must give the one-line --set that turns an add-on off")
    assert "preserved" in text, (
        "NOTES.txt must say which add-ons were kept because they were already "
        "running -- that is the whole point of the three-state default")
    assert 'include "datapond.addonState"' in text, (
        "NOTES.txt must ask _addons.tpl why each add-on resolved as it did rather than "
        "re-deriving explicitness with its own read of the flag -- that second copy is "
        "the one shape the name-based scan cannot see, because it walks the eight by "
        "variable and names none of them")


# ---------------------------------------------------------------------------
# Which add-ons a profile renders, as an assertion.
#
# Expected sets verified directly against `helm template` output for each profile
# (not assumed from the profile files' prose):
#   - base values.yaml, values-foundation.yaml, values-prod-single.yaml,
#     values-aws.yaml and values-ephemeral.yaml render none of the eight. base and
#     values-aws.yaml are the two that moved when the base defaults went to unset;
#     foundation, prod-single and ephemeral state false for all eight themselves.
#   - values-onprem.yaml, values-dev.yaml and values-prod.yaml render all eight, each
#     stating all eight true.
#   - values-quicktest.yaml renders seven of eight -- every add-on except spark, which
#     it explicitly sets to false.
#
# values-dev.yaml and values-prod.yaml used to state only six, leaving trino and
# polaris unset -- so both lost the catalog and query engines they had always rendered
# when the base default moved. The design's own constraint is that a profile stating
# its values is unaffected; a profile carrying the full stack has to state all eight.
# The first version of this table recorded dev's loss as the expected answer and left
# values-prod.yaml and values-ephemeral.yaml out altogether, so the check added to
# catch that movement wrote it down as intended instead.
# ---------------------------------------------------------------------------

ALL_ADDONS = frozenset(ADDONS)

PROFILE_EXPECTATIONS = {
    None: frozenset(),  # base values.yaml, no --values override
    "values-foundation.yaml": frozenset(),
    "values-prod-single.yaml": frozenset(),
    "values-aws.yaml": frozenset(),
    "values-ephemeral.yaml": frozenset(),
    "values-onprem.yaml": ALL_ADDONS,
    "values-dev.yaml": ALL_ADDONS,
    "values-prod.yaml": ALL_ADDONS,
    "values-quicktest.yaml": ALL_ADDONS - {"spark"},
}


def test_every_profile_in_the_chart_is_in_the_table():
    """A profile left out of the table is a profile whose add-on set nothing checks --
    which is how values-prod.yaml silently lost trino and polaris."""
    on_disk = {p.name for p in CHART.glob("values-*.yaml")}
    listed = {p for p in PROFILE_EXPECTATIONS if p}
    assert on_disk == listed, (
        f"profiles on disk but not in PROFILE_EXPECTATIONS: {sorted(on_disk - listed)}; "
        f"listed but missing on disk: {sorted(listed - on_disk)}")


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


@pytest.mark.parametrize("profile", sorted(PROFILE_EXPECTATIONS, key=lambda p: p or ""))
def test_a_rendered_addon_keeps_its_dependencies(profile):
    """A workload that renders while its ingress path, ServiceAccount or PVC does not
    is the exact failure the direct `.Values.<component>.enabled` reads produced. This
    pins the two directions together per profile."""
    # component -> (ingress path, ServiceAccount name, other object that must accompany it)
    DEPENDENCIES = {
        "airflow": ("/airflow", None, None),
        "jupyter": ("/jupyter", "datapond-jupyter", None),
        "mlflow": ("/mlflow", "datapond-mlflow", None),
        "spark": ("/spark", "datapond-spark", None),
        "trino": ("/trino", "datapond-trino", "iceberg-warehouse-pvc"),
        "polaris": (None, "datapond-polaris", "iceberg-warehouse-pvc"),
        "risingwave": ("/risingwave", None, None),
        "openmetadata": ("/openmetadata", None, None),
    }
    expected = PROFILE_EXPECTATIONS[profile]
    args = [f"--values={CHART / profile}"] if profile else []
    rendered = helm_template(args)
    label = profile or "values.yaml (base)"
    ingress_rendered = "\nkind: Ingress\n" in rendered

    for component in sorted(expected):
        path, sa, other = DEPENDENCIES[component]
        if path and ingress_rendered:
            assert f"- path: {path}\n" in rendered, (
                f"{label}: {component} renders but its ingress path {path} does not")
        if sa:
            assert sa in rendered_names(rendered, "ServiceAccount"), (
                f"{label}: {component} renders but its ServiceAccount {sa} does not -- "
                f"the pod names it in serviceAccountName")
        if other:
            assert other in rendered, (
                f"{label}: {component} renders but {other} does not")

    for component in sorted(ALL_ADDONS - expected):
        path, _, _ = DEPENDENCIES[component]
        if path and ingress_rendered:
            assert f"- path: {path}\n" not in rendered, (
                f"{label}: {component} does not render but its ingress path {path} "
                f"still does")
