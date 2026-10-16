"use client"

/** How to change this deployment's configuration: Helm values and upgrade commands for
 *  the profile it runs, and the Airflow SMTP setup when pipelines are on. Documentation
 *  filled in from the runtime (profile, namespace), shown in Help → Operate; it was the
 *  Settings → System tab, a page of instructions among settings that act. */
import { useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useCapabilities, useCapability } from "@/lib/capabilities"
import { Activity, AlertCircle, CheckCircle2, Copy, Terminal } from "lucide-react"

const PROFILE_VALUES: Record<string, string> = {
  "oss-extended": "values.yaml",
  "portable-core-aws": "values-foundation.yaml",
  "aws-single-node": "values-prod-single.yaml",
  "aws-hybrid-extended": "values-aws.yaml",
  "sovereign-oss-extended": "values-onprem.yaml",
  development: "values-dev.yaml",
  "quick-test": "values-quicktest.yaml",
  "self-hosted-extended": "values-prod.yaml",
}

function helmCommands(profileId: string, namespace: string) {
  const valuesFile = PROFILE_VALUES[profileId]
  if (!valuesFile || !namespace) return null
  return {
    valuesFile,
    commands: [
      { label: "Check current values", cmd: `helm get values datapond -n ${namespace}` },
      { label: `Upgrade (${valuesFile})`, cmd: `helm upgrade datapond helm/datapond \\\n  --namespace ${namespace} \\\n  --values helm/datapond/${valuesFile} \\\n  --wait=false` },
      { label: "Pod status", cmd: `kubectl get pods -n ${namespace}` },
      { label: "Resource usage", cmd: `kubectl top pods -n ${namespace}` },
      { label: "Backend logs", cmd: `kubectl logs -f deployment/backend -n ${namespace}` },
    ],
  }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0"
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
      {copied ? <CheckCircle2 className="h-3 w-3 text-[var(--dp-good-text)]" /> : <Copy className="h-3 w-3 text-muted-foreground" />}
    </Button>
  )
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  return (
    <div className="rounded-md border overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-muted/40 border-b">
        <span className="text-2xs text-muted-foreground font-medium">{label}</span>
        <CopyButton text={code} />
      </div>
      <pre className="px-3 py-2.5 text-2xs font-mono overflow-x-auto whitespace-pre leading-relaxed">{code}</pre>
    </div>
  )
}

export function DeploymentConfig() {
  const caps = useCapabilities()
  const runtimeProfileId = typeof caps.profile_id === "string" ? caps.profile_id : ""
  const deploymentNamespace = typeof caps.deployment_namespace === "string" ? caps.deployment_namespace : ""
  const helmConfig = helmCommands(runtimeProfileId, deploymentNamespace)
  const valuesFile = helmConfig?.valuesFile
  const commands = helmConfig?.commands ?? []
  const pipelinesEnabled = useCapability("pipelines")

  return (
    <div className="space-y-5">
            {/* Helm configuration */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-muted-foreground" />Configuration Management
                </CardTitle>
                <CardDescription>Helm-based configuration workflow</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {helmConfig ? (
                  <>
                    <div className="rounded-lg bg-muted/40 border px-4 py-3 text-xs space-y-1.5">
                      <p className="font-medium">How to apply changes</p>
                      <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
                        <li>Edit <code className="bg-background rounded px-1">helm/datapond/{valuesFile}</code> or your deployment-specific overlay</li>
                        <li>Run the upgrade command below</li>
                        <li>Wait for workloads to restart and verify</li>
                      </ol>
                    </div>
                    <div className="space-y-2">
                      {commands.map(({ label, cmd }) => (
                        <CodeBlock key={label} label={label} code={cmd} />
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="rounded-lg border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/5 px-4 py-3 text-xs text-[var(--dp-warn-text)]">
                    Runtime profile identity or namespace is unavailable/custom. Upgrade commands are suppressed; use the values files and namespace from your actual deployment pipeline.
                  </div>
                )}
              </CardContent>
            </Card>

            {/* SMTP — Airflow-based, only relevant when pipelines (Airflow) is deployed */}
            {pipelinesEnabled && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Activity className="h-4 w-4 text-muted-foreground" />Email Alerts (SMTP)
                </CardTitle>
                <CardDescription>Configure Airflow SMTP for pipeline failure notifications</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3 rounded-lg border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/5 px-4 py-3">
                  <AlertCircle className="h-4 w-4 text-[var(--dp-warn-text)] shrink-0" />
                  <p className="text-xs text-[var(--dp-warn-text)]"><span className="font-medium">Operator configuration</span> — {helmConfig ? "use the steps below to enable or update email notifications." : "use your deployment pipeline to configure SMTP safely."}</p>
                </div>

                {helmConfig ? (
                  <>
                    <CodeBlock label="Step 1 — Store SMTP password as K8s Secret"
                      code={`kubectl create secret generic datapond-secrets -n ${deploymentNamespace} \\\n  --from-literal=AIRFLOW_SMTP_PASSWORD="your-password" \\\n  --dry-run=client -o yaml | kubectl apply -f -`} />

                    <CodeBlock label={`Step 2 — Add to ${valuesFile}`}
                      code={`airflow:\n  smtp:\n    enabled: true\n    host: "smtp.gmail.com"\n    port: "587"\n    user: "alerts@company.com"\n    mailFrom: "DataPond <alerts@company.com>"`} />

                    <CodeBlock label="Step 3 — Apply with Helm upgrade"
                      code={`helm upgrade datapond helm/datapond -n ${deploymentNamespace} --values helm/datapond/${valuesFile} --wait=false`} />
                  </>
                ) : (
                  <div className="rounded-lg border px-4 py-3 text-xs text-muted-foreground">
                    Commands are suppressed because this runtime does not report a maintained profile and namespace. Apply SMTP settings through your actual deployment overlay and secret-management workflow.
                  </div>
                )}

                <div>
                  <p className="text-xs font-medium mb-2">Common SMTP providers</p>
                  <div className="space-y-1.5">
                    {[
                      { name: "Gmail",       host: "smtp.gmail.com",                              port: "587", note: "Requires App Password (Google Account → Security → 2FA → App passwords)" },
                      { name: "Office 365",  host: "smtp.office365.com",                          port: "587", note: "Use corporate Microsoft 365 account" },
                      { name: "AWS SES",     host: "email-smtp.ap-northeast-2.amazonaws.com",     port: "587", note: "Create IAM SMTP credentials in SES console" },
                      { name: "On-prem SMTP",host: "mail.company.com",                            port: "25",  note: "Request SMTP relay from IT team" },
                    ].map(p => (
                      <div key={p.name} className="rounded-md border px-3 py-2 text-xs">
                        <div className="flex items-center gap-3">
                          <span className="font-medium w-24 shrink-0">{p.name}</span>
                          <code className="text-muted-foreground">{p.host}:{p.port}</code>
                        </div>
                        <p className="text-2xs text-muted-foreground mt-0.5">{p.note}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
            )}
    </div>
  )
}
