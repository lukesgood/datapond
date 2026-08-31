{{/*
storageClassName, or nothing at all.

An empty value used to render `storageClassName:` — which is null, which Kubernetes
reads as "use the default" *at creation* and then replaces with the real class. On the
next upgrade Helm's manifest still said null, it tried to patch the field back, and
the API server refused:

    PersistentVolumeClaim "valkey-pvc" is invalid:
      spec: Forbidden: spec is immutable after creation

The install worked and the upgrade failed, on a profile that had done nothing wrong
except decline to pin a storage class. Omitting the key entirely leaves the API
server's value alone, which is what "use the default" has to mean on both paths.

Usage, with the value and the indent:

    {{- include "datapond.storageClassName" (dict "value" .Values.global.storageClass "indent" 2) }}
*/}}
{{- define "datapond.storageClassName" -}}
{{- $value := .value | default "" -}}
{{- if $value }}
{{ repeat (int (.indent | default 2)) " " }}storageClassName: {{ $value | quote }}
{{- end -}}
{{- end -}}
