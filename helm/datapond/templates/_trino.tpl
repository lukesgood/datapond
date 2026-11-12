{{/*
trino.extraCatalogs — one Trino catalog file per additional Iceberg REST catalog.

DataPond's catalog registry (Settings → Data catalogs) lists and governs a catalog;
queries against it run on the engine, which knows only the catalogs it has a file for.
Each entry here renders `<name>.properties` into the trino-catalog ConfigMap; `name`
must equal the registry entry's engine catalog.

Credentials never appear in values: `credentialSecret` (OAuth2 client credential,
`id:secret`, or only the secret when `credentialSecret.clientId` names the id) or `tokenSecret` (bearer token) name a Kubernetes Secret key, injected as
an env var and referenced as ${ENV:...} — the pattern iceberg.properties already uses
for the Polaris client secret.
*/}}

{{- define "datapond.trinoExtraCatalogs.validate" -}}
{{- $seen := dict -}}
{{- range $c := (.Values.trino.extraCatalogs | default list) -}}
{{- $name := toString ($c.name | default "") -}}
{{- if not (regexMatch "^[a-z][a-z0-9_]{0,63}$" $name) -}}
{{- fail (printf "trino.extraCatalogs: name %q must be lowercase letters, digits and _ (it is the Trino catalog name and the registry entry's engine catalog)" $name) -}}
{{- end -}}
{{- if has $name (list "iceberg" "postgres" "system" "jmx" "memory" "tpch") -}}
{{- fail (printf "trino.extraCatalogs: name %q is already a catalog of this chart" $name) -}}
{{- end -}}
{{- if hasKey $seen $name -}}
{{- fail (printf "trino.extraCatalogs: name %q is listed twice" $name) -}}
{{- end -}}
{{- $_ := set $seen $name true -}}
{{- if ne (toString ($c.type | default "rest")) "rest" -}}
{{- fail (printf "trino.extraCatalogs[%s]: only type rest (Iceberg REST) is supported" $name) -}}
{{- end -}}
{{- range $k := (list "credential" "token" "password" "secret" "clientSecret") -}}
{{- if hasKey $c $k -}}
{{- fail (printf "trino.extraCatalogs[%s]: %s must not be in values; put it in a Kubernetes Secret and use credentialSecret / tokenSecret" $name $k) -}}
{{- end -}}
{{- end -}}
{{- $uri := toString ($c.uri | default "") -}}
{{- if not (or (hasPrefix "https://" $uri) (regexMatch "^http://(localhost|[^/:@]+\\.svc(\\.cluster\\.local)?)(:[0-9]+)?(/|$)" $uri)) -}}
{{- fail (printf "trino.extraCatalogs[%s]: uri must be https (http only for *.svc / *.svc.cluster.local), got %q" $name $uri) -}}
{{- end -}}
{{- if contains "@" (regexReplaceAll "^[a-z]+://([^/]*).*$" $uri "${1}") -}}
{{- fail (printf "trino.extraCatalogs[%s]: uri must not carry credentials" $name) -}}
{{- end -}}
{{- if $c.s3Endpoint -}}
{{- $ep := toString $c.s3Endpoint -}}
{{- if not (regexMatch "^https?://[^/@\\s]+(/|$)" $ep) -}}
{{- fail (printf "trino.extraCatalogs[%s]: s3Endpoint must be an http(s) URL without credentials, got %q" $name $ep) -}}
{{- end -}}
{{- end -}}
{{- if and $c.credentialSecret $c.tokenSecret -}}
{{- fail (printf "trino.extraCatalogs[%s]: set credentialSecret or tokenSecret, not both" $name) -}}
{{- end -}}
{{- if and $c.credentialSecret $c.credentialSecret.clientId (not (regexMatch "^[A-Za-z0-9_.-]{1,128}$" (toString $c.credentialSecret.clientId))) -}}
{{- fail (printf "trino.extraCatalogs[%s]: credentialSecret.clientId must be a plain client id (no ':')" $name) -}}
{{- end -}}
{{- range $s := (list $c.credentialSecret $c.tokenSecret) -}}
{{- if and $s (not (and $s.name $s.key)) -}}
{{- fail (printf "trino.extraCatalogs[%s]: a secret reference needs name and key" $name) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "datapond.trinoExtraCatalogs.env" -}}
{{- range $c := (.Values.trino.extraCatalogs | default list) }}
{{- if $c.credentialSecret }}
- name: TRINO_CATALOG_{{ upper $c.name }}_CREDENTIAL
  valueFrom:
    secretKeyRef:
      name: {{ $c.credentialSecret.name }}
      key: {{ $c.credentialSecret.key }}
{{- end }}
{{- if $c.tokenSecret }}
- name: TRINO_CATALOG_{{ upper $c.name }}_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ $c.tokenSecret.name }}
      key: {{ $c.tokenSecret.key }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "datapond.trinoExtraCatalogs.files" -}}
{{- $root := . -}}
{{- range $c := (.Values.trino.extraCatalogs | default list) }}
{{ $c.name }}.properties: |
  connector.name=iceberg
  iceberg.catalog.type=rest
  iceberg.rest-catalog.uri={{ $c.uri }}
  {{- if $c.warehouse }}
  iceberg.rest-catalog.warehouse={{ $c.warehouse }}
  {{- end }}
  {{- if $c.prefix }}
  iceberg.rest-catalog.prefix={{ $c.prefix }}
  {{- end }}
  {{- if and $c.sigv4 $c.sigv4.enabled }}
  iceberg.rest-catalog.security=SIGV4
  iceberg.rest-catalog.signing-name={{ $c.sigv4.signingName | default "execute-api" }}
  {{- else if or $c.credentialSecret $c.tokenSecret }}
  iceberg.rest-catalog.security=OAUTH2
  {{- if $c.credentialSecret }}
  iceberg.rest-catalog.oauth2.credential={{ if $c.credentialSecret.clientId }}{{ $c.credentialSecret.clientId }}:{{ end }}${ENV:TRINO_CATALOG_{{ upper $c.name }}_CREDENTIAL}
  {{- else }}
  iceberg.rest-catalog.oauth2.token=${ENV:TRINO_CATALOG_{{ upper $c.name }}_TOKEN}
  {{- end }}
  {{- if $c.scope }}
  iceberg.rest-catalog.oauth2.scope={{ $c.scope }}
  {{- end }}
  {{- end }}
  {{- if $c.vendedCredentials }}
  iceberg.rest-catalog.vended-credentials-enabled=true
  {{- end }}
  iceberg.register-table-procedure.enabled=true
  fs.native-s3.enabled=true
  {{- /* An S3-compatible store (MinIO) needs its endpoint and path-style addressing;
         AWS S3 (S3 Tables, Glue) needs neither, so both are opt-in per catalog. */}}
  {{- if $c.s3Endpoint }}
  s3.endpoint={{ $c.s3Endpoint }}
  {{- end }}
  {{- if $c.s3PathStyleAccess }}
  s3.path-style-access=true
  {{- end }}
  s3.region={{ $c.s3Region | default ($root.Values.storage.region | default "us-east-1") }}
{{- end }}
{{- end -}}

{{/*
Trino source catalogs (Phase 2): the two Secrets the backend projects connector
credentials into. `trino-source-catalogs` holds one `<catalog>.properties` per
Trino-backed connection (passwords referenced as ${ENV:...}); `trino-source-credentials`
holds those env values. The chart creates both empty and keeps whatever data they
already carry across upgrades; only the backend writes them (rbac-backend.yaml).
*/}}
{{- define "datapond.trinoSourceCatalogsSecret" -}}
{{- dig "sourceCatalogs" "catalogsSecret" "trino-source-catalogs" (.Values.trino | default dict) -}}
{{- end -}}

{{- define "datapond.trinoSourceCredentialsSecret" -}}
{{- dig "sourceCatalogs" "credentialsSecret" "trino-source-credentials" (.Values.trino | default dict) -}}
{{- end -}}

{{/*
The Trino container's environment, shared by the coordinator and the workers: object
storage, catalog credentials and the projected source-catalog passwords. One definition,
so a worker can never miss a credential the coordinator's catalogs reference.
*/}}
{{- define "datapond.trinoPodEnv" -}}
env:
{{- if .Values.storage.endpoint }}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: datapond-secrets
      key: SEAWEEDFS_S3_USER
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: datapond-secrets
      key: SEAWEEDFS_S3_PASSWORD
{{- end }}
- name: AWS_REGION
  value: "{{ .Values.storage.region | default "us-east-1" }}"
{{- if .Values.postgres.enabled }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: datapond-secrets
      key: POSTGRES_PASSWORD
{{- end }}
{{- if (include "datapond.addonOn" (dict "root" $ "component" "polaris")) }}
- name: POLARIS_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: datapond-secrets
      key: POLARIS_CLIENT_SECRET
{{- end }}
{{- if .Values.trino.extraCatalogs }}
{{- include "datapond.trinoExtraCatalogs.env" . | trim | nindent 0 }}
{{- end }}
# Source-catalog passwords, referenced as ${ENV:SRC_<SLUG>_PASSWORD} from the
# projected catalog files. Optional: empty until the first source is added.
envFrom:
- secretRef:
    name: {{ include "datapond.trinoSourceCredentialsSecret" . }}
    optional: true
{{- end -}}
