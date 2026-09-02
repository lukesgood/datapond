{{/*
Whether an optional add-on renders: explicit → already running → off.

Helm cannot tell an explicit `false` from a defaulted one, so `enabled` is three-state
here. `true` runs it, `false` removes it, and *unset* means "keep it if this namespace
is already running it, otherwise off" — which is what stops an upgrade from deleting
workloads out of a deployment that never chose. Same shape as the explicit → existing →
generated rule templates/secrets.yaml uses for passwords.

`kind` is required at every call site, with no default. A default (e.g. "Deployment")
is how the next add-on shaped like Spark inherits this bug silently: Spark's guarded
template creates no Deployment at all, only two StatefulSets, so a lookup defaulted to
"Deployment" would never find it running, "unset" would always resolve to "off", and an
existing install running Spark by default would lose it on the very first upgrade to
this chart version — invisibly, since `helm template` has no cluster and the render
looks identical either way. Naming the kind at the call site is what a reviewer actually
checks against the template it guards.

Args: dict "root" $ "component" "<values key>" "kind" "<the object kind that template
certainly renders whenever the component is on>" "name" "<that object's exact
metadata.name — built from .Values.<component>.name, not a literal>"
*/}}
{{- define "datapond.addonEnabledOrPreserved" -}}
{{- $kind := required "datapond.addonEnabledOrPreserved: \"kind\" is required (no default) -- every call site must name the object kind its component's template actually renders" .kind -}}
{{- $values := (index .root.Values .component) | default dict -}}
{{- $explicit := index $values "enabled" -}}
{{- if kindIs "bool" $explicit -}}
{{- $explicit -}}
{{- else -}}
{{- if lookup "apps/v1" $kind (.root.Values.namespace | default "datapond") .name -}}true{{- else -}}false{{- end -}}
{{- end -}}
{{- end -}}
