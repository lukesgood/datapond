{{- /*
  S3-compatible storage (MinIO): Polaris' own FileIO writes table metadata and would
  address the bucket virtual-host style (iceberg.minio), which resolves only where the
  CoreDNS override is imported (k3s). On any other cluster every commit failed with
  UnknownHostException. A catalog created on MinIO names the endpoint and asks for
  path-style access instead, and says the store has no STS. These are read only on
  Polaris' credential path, which SKIP_CREDENTIAL_SUBSCOPING_INDIRECTION bypasses — so
  polaris-deployment.yaml turns that flag off for S3-compatible storage (this is how
  Polaris' own S3-compatible integration tests run). Native S3 is unchanged.
  Used inside a shell double-quoted JSON string, hence the escaped quotes.
*/ -}}
{{- define "datapond.polarisS3Compat" -}}
{{- if .Values.storage.endpoint -}}
,\"endpoint\":\"http://{{ .Values.storage.endpoint }}\",\"pathStyleAccess\":true,\"stsUnavailable\":true
{{- end -}}
{{- end -}}

{{- /* The same storage config as a JSON object, for updating a catalog that exists. */ -}}
{{- define "datapond.polarisStorageUpdate" -}}
{\"storageType\":\"S3\",\"allowedLocations\":[\"$1\"],\"roleArn\":\"arn:aws:iam::000000000000:role/polaris\"{{ include "datapond.polarisS3Compat" . }}}
{{- end -}}
