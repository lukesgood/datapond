{{/*
The AWS reference (catalog.backend=glue) has no serverless engine any more: SQL, the
catalog preview and dashboards run on the in-cluster Trino (2.4; Athena was removed).
A release whose stored values still say trino.enabled=false — every release installed
before 2.4, since `helm upgrade --reset-then-reuse-values` carries them forward —
would render a backend with no engine behind it. Refuse instead of rendering it.
*/}}
{{- define "datapond.engineGuard" -}}
{{- if and (eq ((.Values.catalog | default dict).backend | default "polaris") "glue") (not (include "datapond.addonOn" (dict "root" . "component" "trino"))) -}}
{{- fail "catalog.backend=glue needs Trino: set trino.enabled=true (the AWS reference runs Trino in-cluster since 2.4; Athena was removed — see docs/UPGRADING.md)" -}}
{{- end -}}
{{- end -}}
