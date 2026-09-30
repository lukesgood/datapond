{{/*
trino.extraCatalogs — one Trino catalog file per additional Iceberg REST catalog.

DataPond's catalog registry (Settings → Data catalogs) lists and governs a catalog;
queries against it run on the engine, which knows only the catalogs it has a file for.
Each entry here renders `<name>.properties` into the trino-catalog ConfigMap; `name`
must equal the registry entry's engine catalog.

Credentials never appear in values: `credentialSecret` (OAuth2 client credential,
`id:secret`) or `tokenSecret` (bearer token) name a Kubernetes Secret key, injected as
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
{{- if and $c.credentialSecret $c.tokenSecret -}}
{{- fail (printf "trino.extraCatalogs[%s]: set credentialSecret or tokenSecret, not both" $name) -}}
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
  iceberg.rest-catalog.oauth2.credential=${ENV:TRINO_CATALOG_{{ upper $c.name }}_CREDENTIAL}
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
  fs.native-s3.enabled=true
  s3.region={{ $c.s3Region | default ($root.Values.storage.region | default "us-east-1") }}
{{- end }}
{{- end -}}
