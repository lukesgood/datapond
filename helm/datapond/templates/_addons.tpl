{{/*
Whether an optional add-on renders: explicit → already running → off.

Helm cannot tell an explicit `false` from a defaulted one, so `enabled` is three-state
here. `true` runs it, `false` removes it, and *unset* means "keep it if this namespace
is already running it, otherwise off" — which is what stops an upgrade from deleting
workloads out of a deployment that never chose. Same shape as the explicit → existing →
generated rule templates/secrets.yaml uses for passwords.

THE RULE THIS FILE ENFORCES: nothing outside this file may read
`.Values.<add-on>.enabled`. An unset flag is `null`, and `null` is falsy to every
two-state reader — a bare `{{ if .Values.trino.enabled }}` guard, a `dig "enabled" true`
default, a `(dict "enabled" .Values.spark.enabled)` list entry. The first version of this
mechanism taught only the eight workload templates about the third state, and the twenty
other sites that read the same flags kept their two-state reading. The result was a chart
that preserved a running add-on while deleting the ingress path, ServiceAccount, secret
key, database and PVC it depends on — and a backend told all eight add-ons were on while
none rendered, because `dig` never sees a key Helm dropped during null coalescing.

So the resolution happens exactly once, here, and every consumer asks the same question
about a component *by name only*. There is no `kind` or `name` argument to get wrong at a
call site, because those live in `datapond.addonTargets` below — one row per add-on,
checked against the template that renders it by
backend/tests/test_helm_addon_defaults.py.

Three entry points, one derivation:

  datapond.addonState              -> why, not just whether: "explicit-on",
      "explicit-off", "preserved" or "off". NOTES.txt needs the reason to report it, and
      asking for it is what stops NOTES.txt from re-deriving explicitness with its own
      `index ... "enabled"` — a second copy of this rule, in the one shape a name-based
      scan cannot see (it walks the eight by variable and names none of them).

  datapond.addonEnabledOrPreserved -> the literal string "true" or "false".
      For a value: `value: "{{ include "datapond.addonEnabledOrPreserved" (dict "root" $ "component" "trino") }}"`

  datapond.addonOn                 -> non-empty when on, empty when off.
      For a guard: `{{- if include "datapond.addonOn" (dict "root" $ "component" "trino") }}`
      Empty-vs-non-empty composes with `and`/`or`/`not`, which `"false"` (a non-empty,
      therefore truthy, string) does not.

Both take `dict "root" $ "component" "<values key>"`.
*/}}

{{/*
The namespace this release's objects actually land in — the namespace the preserve
lookup must search. `.Values.namespace` wins when set (the chart's own convention: every
template writes `metadata.namespace: {{ .Values.namespace }}`), otherwise the namespace
`helm --namespace` installed into. A release installed with `--namespace foo` and an
empty `namespace:` value used to make _addons.tpl look in "datapond" while NOTES.txt
reported on "foo", so the two disagreed about the same release.
*/}}
{{- define "datapond.namespace" -}}
{{- .Values.namespace | default .Release.Namespace -}}
{{- end -}}

{{/*
The eight add-ons, and for each one the single object its template renders
unconditionally — behind only that component's own guard, never behind a second flag.
That object's (kind, name) is what the preserve lookup searches for, so it has to be one
that certainly exists whenever the component is on.

`kind` is per-row and not defaulted. Spark is why: `spark-statefulset.yaml` creates no
Deployment at all, only `spark-master` and `spark-worker` StatefulSets. A lookup
defaulted to "Deployment" would never find Spark running, so "unset" would always
resolve to "off" and an existing install running Spark by default would lose it on the
very first upgrade — invisibly, since `helm template` has no cluster and the render looks
identical either way.

Names are built from `.Values.<component>.name` rather than written as literals, so a
renamed component moves the lookup with it.
*/}}
{{- define "datapond.addonTargets" -}}
{{- $v := .Values -}}
{{- $t := dict -}}
{{- $_ := set $t "airflow"      (dict "kind" "Deployment"  "name" (printf "%s-webserver" (dig "name" "airflow"    ($v.airflow      | default dict)))) -}}
{{- $_ := set $t "spark"        (dict "kind" "StatefulSet" "name" (printf "%s-master"    (dig "name" "spark"      ($v.spark        | default dict)))) -}}
{{- $_ := set $t "polaris"      (dict "kind" "Deployment"  "name"                        (dig "name" "polaris"    ($v.polaris      | default dict))) -}}
{{- $_ := set $t "risingwave"   (dict "kind" "Deployment"  "name" (printf "%s-frontend"  (dig "name" "risingwave" ($v.risingwave   | default dict)))) -}}
{{- $_ := set $t "openmetadata" (dict "kind" "Deployment"  "name" (printf "%s-server"    (dig "name" "openmetadata" ($v.openmetadata | default dict)))) -}}
{{- $_ := set $t "jupyter"      (dict "kind" "Deployment"  "name"                        (dig "name" "jupyterlab" ($v.jupyter      | default dict))) -}}
{{- $_ := set $t "mlflow"       (dict "kind" "Deployment"  "name"                        (dig "name" "mlflow"     ($v.mlflow       | default dict))) -}}
{{- $_ := set $t "trino"        (dict "kind" "Deployment"  "name"                        (dig "name" "trino"      ($v.trino        | default dict))) -}}
{{- $t | toJson -}}
{{- end -}}

{{/*
Resolve one add-on, and say why: "explicit-on", "explicit-off", "preserved" or "off".

This is the only place the flag itself is read. Everything else -- the two entry points
below, and NOTES.txt's report -- switches on the string this returns, so there is one
`index ... "enabled"` in the chart and one `lookup`.
*/}}
{{- define "datapond.addonState" -}}
{{- $root := required "datapond.addonState: \"root\" is required -- pass (dict \"root\" $ \"component\" \"<name>\")" .root -}}
{{- $component := required "datapond.addonState: \"component\" is required" .component -}}
{{- $targets := fromJson (include "datapond.addonTargets" $root) -}}
{{- if not (hasKey $targets $component) -}}
{{- fail (printf "datapond.addonState: %q is not one of the optional add-ons (%s). Only these eight carry the three-state enabled flag; everything else is a plain boolean read directly." $component (keys $targets | sortAlpha | join ", ")) -}}
{{- end -}}
{{- $target := index $targets $component -}}
{{- $explicit := index ((index $root.Values $component) | default dict) "enabled" -}}
{{- if kindIs "bool" $explicit -}}
{{- if $explicit -}}explicit-on{{- else -}}explicit-off{{- end -}}
{{- else if lookup "apps/v1" $target.kind (include "datapond.namespace" $root) $target.name -}}
preserved
{{- else -}}
off
{{- end -}}
{{- end -}}

{{/*
Resolve one add-on. Returns the string "true" or "false".
*/}}
{{- define "datapond.addonEnabledOrPreserved" -}}
{{- $state := include "datapond.addonState" . -}}
{{- if or (eq $state "explicit-on") (eq $state "preserved") -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{/*
The same answer shaped for `{{- if }}`: non-empty when on, empty when off.
*/}}
{{- define "datapond.addonOn" -}}
{{- if eq (include "datapond.addonEnabledOrPreserved" .) "true" -}}on{{- end -}}
{{- end -}}
