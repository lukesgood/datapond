{{/*
Pod and container security contexts.

Every workload ran with the cluster defaults: root allowed, every Linux capability
present, privilege escalation permitted, no seccomp filter. Six pods, none with a
security context of any kind.

Two templates rather than one, because the images differ in what they can take:

  datapond.podSecurity        — needs a numeric UID. Use for images this repo builds
                                (backend, frontend), where the UID is known and
                                already non-root.
  datapond.containerSecurity  — no privilege escalation, no capabilities, the
                                default seccomp filter. Use for third-party images
                                whose user we do not control. Takes an optional
                                `keep` list, because "drop ALL" is not in fact safe
                                for any image: valkey's entrypoint starts as root and
                                lowers itself in steps, and each step needs one —
                                setpriv needs SETUID and SETGID, and the chown of its
                                data directory needs CHOWN. Both were found the same
                                way, as a CrashLoop, the second hiding behind the
                                first: with setpriv already failing the entrypoint
                                never reached the chown. Keeping exactly the
                                capabilities an image uses to become non-root is still
                                a drop from fourteen to three.

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
{{- $enabled := . -}}
{{- $keep := list -}}
{{- if kindIs "map" . -}}
{{- $enabled = .enabled -}}
{{- $keep = .keep | default list -}}
{{- end -}}
{{- if $enabled }}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
    {{- if $keep }}
    add: {{ toJson $keep }}
    {{- end }}
  seccompProfile:
    type: RuntimeDefault
{{- end }}
{{- end -}}
