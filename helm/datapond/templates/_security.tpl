{{/*
Pod and container security contexts.

Every workload ran with the cluster defaults: root allowed, every Linux capability
present, privilege escalation permitted, no seccomp filter. Six pods, none with a
security context of any kind.

Two templates rather than one, because the images differ in what they can take:

  datapond.podSecurity        — needs a numeric UID. Use for images this repo builds
                                (backend, frontend), where the UID is known and
                                already non-root.
  datapond.containerSecurity  — the part that is safe for any image: no privilege
                                escalation, no capabilities, the default seccomp
                                filter. Use for third-party images whose user we do
                                not control.

runAsNonRoot without runAsUser is a trap: both Dockerfiles say `USER <name>`, and
kubelet refuses to start a container it cannot prove is non-root from a name alone
("image has non-numeric user"). The UID has to be spelled out, so it is.
*/}}

{{- define "datapond.podSecurity" -}}
{{- $ctx := . -}}
{{- if $ctx.enabled }}
securityContext:
  runAsNonRoot: true
  runAsUser: {{ $ctx.uid }}
  runAsGroup: {{ $ctx.gid }}
  fsGroup: {{ $ctx.gid }}
  seccompProfile:
    type: RuntimeDefault
{{- end }}
{{- end -}}

{{- define "datapond.containerSecurity" -}}
{{- if . }}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
{{- end }}
{{- end -}}
