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
                                for any image: valkey's entrypoint starts as root
                                and drops to its own user with setpriv, which needs
                                SETUID and SETGID. Removing them turned a hardening
                                change into a CrashLoop — observed live, not
                                theorised. Keeping exactly the two capabilities an
                                image uses to become non-root is still a drop from
                                fourteen to two.

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
