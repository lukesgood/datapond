"use client"

import { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { ArrowLeft, Check, Copy, Loader2, X } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { PermissionGate } from "@/components/ui/permission-state"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { SectionError } from "@/components/agents/section"
import { useJson } from "@/components/agents/use-json"
import {
  createAgentBody, describeAccess, effectivePiiMode, PII_MODE_TEXT,
  type AgentPreset, type PiiMode,
} from "@/lib/agents"

export default function NewAgentPage() {
  return (
    <PermissionGate permission="user:manage" label="Agents">
      <NewAgent />
    </PermissionGate>
  )
}

type Options = {
  presets?: AgentPreset[]
  assignable_roles: string[]
  role_permissions?: Record<string, string[]>
  pii_default?: PiiMode
}

type Created = {
  id: string; username: string
  key?: { key: string; scopes: string[]; expires_at: string | null }
}

const CUSTOM = "custom"
const EXPIRY: { label: string; days: number | null }[] = [
  { label: "30 days", days: 30 }, { label: "90 days", days: 90 },
  { label: "1 year", days: 365 }, { label: "Never", days: null },
]

function NewAgent() {
  const opts = useJson<Options>("/api/service-accounts")
  const [created, setCreated] = useState<Created | null>(null)

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        <Link href="/agents" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" />All agents
        </Link>
        {opts.loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading…</div>
        ) : !opts.data ? (
          <SectionError message={`Could not load agent options: ${opts.error}`} onRetry={opts.reload} />
        ) : created?.key ? (
          <KeyIssued created={created} />
        ) : (
          <Form opts={opts.data} onCreated={setCreated} />
        )}
      </div>
    </div>
  )
}

function Form({ opts, onCreated }: { opts: Options; onCreated: (c: Created) => void }) {
  const router = useRouter()
  const presets = opts.presets ?? []
  const roles = opts.assignable_roles.length ? opts.assignable_roles : ["ai_engineer"]
  const deployment: PiiMode = opts.pii_default ?? "mask"

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [choice, setChoice] = useState(presets[0]?.id ?? CUSTOM)
  const [role, setRole] = useState(roles.includes("ai_engineer") ? "ai_engineer" : roles[0])
  const [pii, setPii] = useState<PiiMode | null>(null)
  const [piiTouched, setPiiTouched] = useState(false)
  const [keyDays, setKeyDays] = useState<number | null>(90)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const preset = presets.find(p => p.id === choice) ?? null
  const effectiveRole = preset?.role ?? role
  const perms = preset ? preset.scopes : (opts.role_permissions?.[role] ?? [])
  const access = describeAccess(perms)
  // The preset's mode until the admin picks one; the strictest with the deployment applies.
  const own = piiTouched ? pii : (preset?.pii_mode ?? null)
  const applies = effectivePiiMode(own, deployment)
  const username = `svc-${name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "-")}`.slice(0, 64)
  const expiryLabel = keyDays === null ? "never expires" : EXPIRY.find(e => e.days === keyDays)?.label ?? `${keyDays} days`

  const create = async () => {
    if (!name.trim() || busy) return
    setBusy(true); setErr(null)
    try {
      const res = await fetch("/api/service-accounts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(createAgentBody(name, description, preset ? { preset } : { role }, own, piiTouched, keyDays)),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) { setErr(typeof d.detail === "string" ? d.detail : `Could not create the agent (HTTP ${res.status})`); return }
      if (d.key?.key) onCreated(d)
      else router.push(`/agents/${d.id}`)
    } finally { setBusy(false) }
  }

  return (
    <>
      <div>
        <h2 className="text-2xl font-bold tracking-tight">New agent</h2>
        <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
          An identity for one application or agent. It gets its own key, sees only what you grant it,
          and is named in spend and audit records.
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <div className="min-w-0 flex-[3_1_520px] space-y-4">
          <section className="space-y-3 rounded-xl border bg-card p-5">
            <div className="flex flex-wrap gap-4">
              <div className="min-w-[220px] flex-1 space-y-1.5">
                <Label htmlFor="agent-name">Name</Label>
                <Input id="agent-name" value={name} onChange={e => setName(e.target.value)} maxLength={64}
                       placeholder="e.g. support-assistant" autoFocus />
                <p className="text-xs text-muted-foreground">
                  Username <code className="font-mono">{name.trim() ? username : "svc-…"}</code>
                </p>
              </div>
              <div className="min-w-[220px] flex-1 space-y-1.5">
                <Label htmlFor="agent-desc">Description <span className="font-normal text-muted-foreground">(optional)</span></Label>
                <Input id="agent-desc" value={description} onChange={e => setDescription(e.target.value)} maxLength={200}
                       placeholder="e.g. Help-center bot on the website" />
                <p className="text-xs text-muted-foreground">Shown as its display name.</p>
              </div>
            </div>
          </section>

          <section className="space-y-3 rounded-xl border bg-card p-5">
            <h3 className="text-sm font-semibold">What is it for?</h3>
            <div role="radiogroup" aria-label="Purpose" className="grid gap-2.5 sm:grid-cols-2">
              {[...presets, null].map(p => {
                const id = p?.id ?? CUSTOM
                const on = choice === id
                return (
                  <button key={id} type="button" role="radio" aria-checked={on} onClick={() => setChoice(id)}
                          className={`flex min-h-[76px] flex-col gap-1 rounded-lg border p-3 text-left transition-colors ${on
                            ? "border-primary bg-primary/5 ring-1 ring-primary" : "bg-card hover:border-primary/50"}`}>
                    <span className="flex items-center gap-2 text-sm font-semibold">
                      <span aria-hidden className={`h-3.5 w-3.5 shrink-0 rounded-full border bg-background ${on ? "border-[4px] border-primary" : "border-muted-foreground/50"}`} />
                      {p ? p.label : "Custom"}
                    </span>
                    <span className="text-xs leading-snug text-muted-foreground">
                      {p ? p.description.split(" — ")[0].split(". ")[0] + "." : "Choose the role yourself; scopes later on the agent's page."}
                    </span>
                  </button>
                )
              })}
            </div>
            {!preset && (
              <div className="space-y-1.5 border-t pt-3">
                <Label htmlFor="agent-role">Role</Label>
                <select id="agent-role" value={role} onChange={e => setRole(e.target.value)}
                        className="h-9 w-full max-w-xs rounded-md border bg-background px-2 text-sm">
                  {roles.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                <p className="text-xs text-muted-foreground">
                  No key is issued yet. You pick its scopes on the agent&apos;s page; a key without scopes can do
                  everything the role allows.
                </p>
              </div>
            )}
          </section>

          <section className="space-y-4 rounded-xl border bg-card p-5">
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">PII guardrail</h3>
              <ChoiceGroup<PiiMode | null> label="PII guardrail" value={own}
                options={[{ label: `Inherit (${deployment})`, value: null }, { label: "mask", value: "mask" }, { label: "block", value: "block" }]}
                onChange={v => { setPii(v); setPiiTouched(true) }} />
              <p className="text-xs text-muted-foreground">Can only make the deployment default stricter.</p>
            </div>
            {preset && (
              <div className="space-y-2 border-t pt-4">
                <h3 className="text-sm font-semibold">First key expires</h3>
                <ChoiceGroup<number | null> label="First key expires" value={keyDays}
                  options={EXPIRY.map(e => ({ label: e.label, value: e.days }))} onChange={setKeyDays} />
                <p className="text-xs text-muted-foreground">You can rotate it, or issue more keys, on the agent&apos;s page.</p>
              </div>
            )}
          </section>

          {err && <SectionError message={err} />}
          <div className="flex items-center gap-2">
            <Button onClick={create} disabled={busy || !name.trim()}>
              {busy && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {preset ? "Create agent and issue key" : "Create agent"}
            </Button>
            <Link href="/agents" className={buttonVariants({ variant: "ghost" })}>Cancel</Link>
          </div>
        </div>

        <aside aria-label="What this agent will be able to do"
               className="min-w-0 flex-[2_1_340px] space-y-4 rounded-xl border bg-muted/40 p-5 lg:sticky lg:top-6">
          <div>
            <p className="text-xs text-muted-foreground">This agent will be</p>
            <h3 className="mt-0.5 text-lg font-bold">{preset ? preset.label : `Custom · ${role}`}</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {preset ? preset.description
                : `Everything the ${role} role allows, until you issue a key with narrower scopes on its page.`}
            </p>
          </div>
          <AccessList title="It can" items={access.can} ok />
          <AccessList title="It cannot" items={access.cannot} />
          <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-2 border-t pt-3 text-sm">
            <dt className="text-muted-foreground">Role</dt><dd className="font-mono text-xs leading-5">{effectiveRole}</dd>
            <dt className="text-muted-foreground">First key</dt>
            <dd>{preset ? <><code className="font-mono text-xs">{preset.scopes.join(", ")}</code> · {expiryLabel}</> : "None yet — issued on the agent's page"}</dd>
            <dt className="text-muted-foreground">PII</dt>
            <dd><span className="rounded-full bg-accent px-2 py-0.5 text-xs font-semibold">applies: {applies}</span>{" "}
              <span className="text-muted-foreground">{PII_MODE_TEXT[applies].split(" — ")[1]}.</span></dd>
          </dl>
          <div className="space-y-1.5 border-t pt-3">
            <h4 className="text-sm font-semibold">After you create it</h4>
            <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
              <li>{preset ? "Copy the key — it is shown once." : "Issue a key and pick its scopes."}</li>
              <li>Grant the collections or catalogs it should read.</li>
              <li>Optional: set a monthly spend cap.</li>
            </ol>
          </div>
        </aside>
      </div>
    </>
  )
}

function AccessList({ title, items, ok }: { title: string; items: string[]; ok?: boolean }) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-sm font-semibold">{title}</h4>
      <ul className="space-y-1">
        {items.map(t => (
          <li key={t} className="flex gap-2 text-sm">
            {ok ? <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-[var(--dp-good-text)]" />
                : <X aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
            <span className={ok ? "" : "text-muted-foreground"}>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function KeyIssued({ created }: { created: Created }) {
  const [copied, setCopied] = useState(false)
  const k = created.key!
  const agentHref = `/agents/${created.id}`
  const steps = [
    { title: "Grant what it should read", text: "Until you do, it reads only collections and catalogs open to everyone.", href: `${agentHref}#access`, cta: "Grant access", primary: true },
    { title: "Set a monthly spend cap", text: "Optional. Over the cap, its model calls are refused with 402.", href: `${agentHref}#spend`, cta: "Set cap" },
    { title: "Connect the agent", text: "REST at /api, or MCP at POST /api/mcp.", href: "/help", cta: "Open guide" },
  ]
  return (
    <>
      <div>
        <h2 className="text-2xl font-bold tracking-tight">{created.username} is ready</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">Copy its key before you leave this page.</p>
      </div>
      <div className="max-w-3xl space-y-4">
        <section className="space-y-3 rounded-xl border-2 border-primary bg-card p-5">
          <h3 className="text-sm font-semibold">Copy its key now</h3>
          <p className="text-sm text-muted-foreground">
            It is stored only as a hash. If you leave without copying it, revoke it and issue another.
          </p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md border bg-muted px-3 py-2 font-mono text-xs">{k.key}</code>
            <Button variant={copied ? "outline" : "default"} className="gap-1.5"
                    onClick={() => { void navigator.clipboard.writeText(k.key); setCopied(true) }}>
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}{copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Send it as <code className="font-mono">Authorization: Bearer &lt;key&gt;</code>. Scopes{" "}
            <code className="font-mono">{k.scopes.join(", ")}</code>{k.expires_at ? `, expires ${k.expires_at.slice(0, 10)}` : ", never expires"}.
          </p>
        </section>
        <section className="rounded-xl border bg-card p-5">
          <h3 className="mb-2 text-sm font-semibold">Next</h3>
          <ol>
            {steps.map((s, i) => (
              <li key={s.title} className="flex items-center gap-3 border-t py-3 first:border-t-0">
                <span aria-hidden className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{s.title}</p>
                  <p className="text-xs text-muted-foreground">{s.text}</p>
                </div>
                <Link href={s.href} className={buttonVariants({ size: "sm", variant: s.primary ? "default" : "outline" })}>{s.cta}</Link>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  )
}
