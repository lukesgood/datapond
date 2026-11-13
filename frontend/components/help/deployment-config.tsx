"use client"

/** How to change this deployment's configuration: Helm values and upgrade commands for
 *  the profile it runs, and the Airflow SMTP setup when pipelines are on. Documentation
 *  filled in from the runtime (profile, namespace), shown in Help → Operate; it was the
 *  Settings → System tab, a page of instructions among settings that act. */
import { useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useCapabilities, useCapability } from "@/lib/capabilities"
import { useHelpLocale } from "@/components/help/locale"
import { Rich, SectionCard } from "@/components/help/ai-ops-guide"
import type { L } from "@/lib/help-locale"
import { OPERATE_PROFILES, OPERATE_PROFILES_NOTE, OPERATE_PROFILES_TITLE, OPERATE_TOPICS } from "@/lib/help-operate"

const l = (en: string, ko: string): L => ({ en, ko })
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
      { label: l("Check current values", "현재 values 확인"), cmd: `helm get values datapond -n ${namespace}` },
      { label: l(`Upgrade (${valuesFile})`, `업그레이드 (${valuesFile})`), cmd: `helm upgrade datapond helm/datapond \\\n  --namespace ${namespace} \\\n  --values helm/datapond/${valuesFile} \\\n  --wait=false` },
      { label: l("Pod status", "파드 상태"), cmd: `kubectl get pods -n ${namespace}` },
      { label: l("Resource usage", "리소스 사용량"), cmd: `kubectl top pods -n ${namespace}` },
      { label: l("Backend logs", "백엔드 로그"), cmd: `kubectl logs -f deployment/backend -n ${namespace}` },
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

function CodeBlock({ label, code }: { label: L | string; code: string }) {
  const { t } = useHelpLocale()
  return (
    <div className="rounded-md border overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-muted/40 border-b">
        <span className="text-2xs text-muted-foreground font-medium">{t(label)}</span>
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
  const { t } = useHelpLocale()

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t(OPERATE_PROFILES_TITLE)}</CardTitle>
          <CardDescription><Rich text={t(OPERATE_PROFILES_NOTE)} /></CardDescription>
        </CardHeader>
        <CardContent className="space-y-1.5">
          {OPERATE_PROFILES.map((p) => (
            <div key={p.file} className="rounded-md border px-3 py-2 text-xs">
              <code className="font-medium">{p.file}</code>
              <p className="text-2xs text-muted-foreground mt-0.5">{t(p.use)}</p>
            </div>
          ))}
        </CardContent>
      </Card>
      {OPERATE_TOPICS.map((s) => <SectionCard key={s.title.en} s={s} />)}
            {/* Helm configuration */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-muted-foreground" />{t(l("Configuration Management", "설정 관리"))}
                </CardTitle>
                <CardDescription>{t(l("Helm-based configuration workflow", "Helm 기반 설정 절차"))}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {helmConfig ? (
                  <>
                    <div className="rounded-lg bg-muted/40 border px-4 py-3 text-xs space-y-1.5">
                      <p className="font-medium">{t(l("How to apply changes", "변경 적용 방법"))}</p>
                      <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
                        <li>{t(l("Edit", "다음 파일을 수정하거나 배포별 오버레이를 사용합니다:"))} <code className="bg-background rounded px-1">helm/datapond/{valuesFile}</code></li>
                        <li>{t(l("Run the upgrade command below", "아래 업그레이드 명령을 실행합니다"))}</li>
                        <li>{t(l("Wait for workloads to restart and verify", "워크로드가 재시작될 때까지 기다린 뒤 확인합니다"))}</li>
                      </ol>
                    </div>
                    <div className="space-y-2">
                      {commands.map(({ label, cmd }) => (
                        <CodeBlock key={label.en} label={label} code={cmd} />
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="rounded-lg border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/5 px-4 py-3 text-xs text-[var(--dp-warn-text)]">
                    {t(l("Runtime profile identity or namespace is unavailable/custom. Upgrade commands are suppressed; use the values files and namespace from your actual deployment pipeline.", "런타임 프로필 또는 네임스페이스를 알 수 없거나 사용자 정의입니다. 업그레이드 명령은 표시하지 않습니다. 실제 배포 파이프라인의 values 파일과 네임스페이스를 사용하세요."))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* SMTP — Airflow-based, only relevant when pipelines (Airflow) is deployed */}
            {pipelinesEnabled && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Activity className="h-4 w-4 text-muted-foreground" />{t(l("Email Alerts (SMTP)", "이메일 알림 (SMTP)"))}
                </CardTitle>
                <CardDescription>{t(l("Configure Airflow SMTP for pipeline failure notifications", "파이프라인 실패 알림을 위한 Airflow SMTP 설정"))}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3 rounded-lg border border-[var(--dp-warn)]/30 bg-[var(--dp-warn)]/5 px-4 py-3">
                  <AlertCircle className="h-4 w-4 text-[var(--dp-warn-text)] shrink-0" />
                  <p className="text-xs text-[var(--dp-warn-text)]"><span className="font-medium">{t(l("Operator configuration", "운영자 설정"))}</span> — {helmConfig ? t(l("use the steps below to enable or update email notifications.", "아래 단계로 이메일 알림을 켜거나 수정합니다.")) : t(l("use your deployment pipeline to configure SMTP safely.", "배포 파이프라인으로 SMTP를 안전하게 설정하세요."))}</p>
                </div>

                {helmConfig ? (
                  <>
                    <CodeBlock label={l("Step 1 — Store SMTP password as K8s Secret", "1단계 — SMTP 비밀번호를 K8s Secret으로 저장")}
                      code={`kubectl create secret generic datapond-secrets -n ${deploymentNamespace} \\\n  --from-literal=AIRFLOW_SMTP_PASSWORD="your-password" \\\n  --dry-run=client -o yaml | kubectl apply -f -`} />

                    <CodeBlock label={l(`Step 2 — Add to ${valuesFile}`, `2단계 — ${valuesFile}에 추가`)}
                      code={`airflow:\n  smtp:\n    enabled: true\n    host: "smtp.gmail.com"\n    port: "587"\n    user: "alerts@company.com"\n    mailFrom: "DataPond <alerts@company.com>"`} />

                    <CodeBlock label={l("Step 3 — Apply with Helm upgrade", "3단계 — Helm 업그레이드로 적용")}
                      code={`helm upgrade datapond helm/datapond -n ${deploymentNamespace} --values helm/datapond/${valuesFile} --wait=false`} />
                  </>
                ) : (
                  <div className="rounded-lg border px-4 py-3 text-xs text-muted-foreground">
                    {t(l("Commands are suppressed because this runtime does not report a maintained profile and namespace. Apply SMTP settings through your actual deployment overlay and secret-management workflow.", "이 런타임이 관리되는 프로필과 네임스페이스를 알려 주지 않아 명령을 표시하지 않습니다. 실제 배포 오버레이와 시크릿 관리 절차로 SMTP를 설정하세요."))}
                  </div>
                )}

                <div>
                  <p className="text-xs font-medium mb-2">{t(l("Common SMTP providers", "자주 쓰는 SMTP 제공자"))}</p>
                  <div className="space-y-1.5">
                    {[
                      { name: "Gmail",       host: "smtp.gmail.com",                              port: "587", note: l("Requires App Password (Google Account → Security → 2FA → App passwords)", "앱 비밀번호가 필요합니다 (Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호)") },
                      { name: "Office 365",  host: "smtp.office365.com",                          port: "587", note: l("Use corporate Microsoft 365 account", "회사 Microsoft 365 계정을 사용합니다") },
                      { name: "AWS SES",     host: "email-smtp.ap-northeast-2.amazonaws.com",     port: "587", note: l("Create IAM SMTP credentials in SES console", "SES 콘솔에서 IAM SMTP 자격 증명을 만듭니다") },
                      { name: "On-prem SMTP",host: "mail.company.com",                            port: "25",  note: l("Request SMTP relay from IT team", "IT 팀에 SMTP 릴레이를 요청합니다") },
                    ].map(p => (
                      <div key={p.name} className="rounded-md border px-3 py-2 text-xs">
                        <div className="flex items-center gap-3">
                          <span className="font-medium w-24 shrink-0">{p.name}</span>
                          <code className="text-muted-foreground">{p.host}:{p.port}</code>
                        </div>
                        <p className="text-2xs text-muted-foreground mt-0.5">{t(p.note)}</p>
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
