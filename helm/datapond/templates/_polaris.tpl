{{- /*
  S3-compatible storage (MinIO): Polaris' own FileIO writes table metadata and would
  address the bucket virtual-host style (iceberg.minio), which resolves only where the
  CoreDNS override is imported (k3s). On any other cluster every commit failed with
  UnknownHostException. A catalog created on MinIO names the endpoint and asks for
  path-style access instead. Native S3 (no storage.endpoint) is unchanged.
  Used inside a shell double-quoted JSON string, hence the escaped quotes.
*/ -}}
{{- define "datapond.polarisS3Compat" -}}
{{- if .Values.storage.endpoint -}}
,\"endpoint\":\"http://{{ .Values.storage.endpoint }}\",\"pathStyleAccess\":true
{{- end -}}
{{- end -}}
