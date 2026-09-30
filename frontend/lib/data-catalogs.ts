/** Form logic for Settings -> Data catalogs (/api/catalogs). Mirrors the backend's
 *  rules (app/catalog_registry.py validate_config, app/api/catalog_admin.py) so an
 *  admin sees the problem before the request; the backend still decides. */

export type CatalogKind = "glue" | "iceberg_rest" | "polaris"
export const KINDS: CatalogKind[] = ["glue", "iceberg_rest", "polaris"]

export const KIND_LABEL: Record<CatalogKind, string> = {
  glue: "AWS Glue",
  iceberg_rest: "Iceberg REST",
  polaris: "Polaris (in-cluster)",
}

export interface DataCatalog {
  name: string
  kind: CatalogKind
  engine_catalog: string
  config: Record<string, string | boolean>
  is_default: boolean
  enabled: boolean
  has_secret: boolean
  reader?: string
}

export interface CatalogForm {
  name: string
  kind: CatalogKind
  engine_catalog: string
  // glue
  region: string
  catalog_id: string
  via_rest: boolean
  role_arn: string
  external_id: string
  // glue / iceberg_rest / polaris
  warehouse: string
  // iceberg_rest
  uri: string
  sigv4: boolean
  signing_name: string
  signing_region: string
  scope: string
  prefix: string
  /** Write-only. Empty means "leave as is" on edit. */
  secret: string
  clearSecret: boolean
  is_default: boolean
  enabled: boolean
}

type ConfigField = "region" | "catalog_id" | "via_rest" | "role_arn" | "external_id" | "warehouse" | "uri" | "sigv4" |
  "signing_name" | "signing_region" | "scope" | "prefix"

/** The config keys each kind carries — the backend's whitelist. */
export const KIND_FIELDS: Record<CatalogKind, ConfigField[]> = {
  glue: ["region", "catalog_id", "warehouse", "via_rest", "role_arn", "external_id"],
  iceberg_rest: ["uri", "warehouse", "sigv4", "signing_name", "signing_region", "scope", "prefix"],
  polaris: ["warehouse"],
}

const BOOL_FIELDS = new Set<ConfigField>(["via_rest", "sigv4"])

export function emptyForm(kind: CatalogKind = "iceberg_rest"): CatalogForm {
  return {
    name: "", kind, engine_catalog: "", region: "", catalog_id: "", via_rest: false, role_arn: "", external_id: "",
    warehouse: "", uri: "", sigv4: false, signing_name: "", signing_region: "", scope: "",
    prefix: "", secret: "", clearSecret: false, is_default: false, enabled: true,
  }
}

export function formFromCatalog(c: DataCatalog): CatalogForm {
  const f = emptyForm(c.kind)
  f.name = c.name
  f.engine_catalog = c.engine_catalog
  f.is_default = c.is_default
  f.enabled = c.enabled
  for (const key of KIND_FIELDS[c.kind]) {
    const v = c.config?.[key]
    if (BOOL_FIELDS.has(key)) (f as unknown as Record<string, unknown>)[key] = v === true
    else if (typeof v === "string") (f as unknown as Record<string, unknown>)[key] = v
  }
  return f
}

const IDENT = /^[A-Za-z0-9_]{1,64}$/
const REGION = /^[a-z]{2}(-[a-z]+)+-\d$/
const ACCOUNT = /^\d{12}$/
const ROLE_ARN = /^arn:aws(-[a-z]+)*:iam::\d{12}:role\/[\w+=,.@/-]{1,128}$/
const EXTERNAL_ID = /^[\w+=,.@:/-]{2,1224}$/
const SIGNING_NAME = /^[a-z0-9-]{1,64}$/

/** null when the uri is acceptable, else why not. https, or http to *.svc,
 *  *.svc.cluster.local or localhost; never with credentials in it. */
export function uriProblem(uri: string): string | null {
  let u: URL
  try { u = new URL(uri) } catch { return "Not a URL." }
  if (u.username || u.password) return "The URL must not carry credentials; use the secret."
  const host = u.hostname.toLowerCase()
  if (!host) return "The URL has no host."
  if (u.protocol === "https:") return null
  if (u.protocol === "http:" && (host === "localhost" || host.endsWith(".svc") ||
      host.endsWith(".svc.cluster.local"))) return null
  return "Must be https (http only for *.svc, *.svc.cluster.local or localhost)."
}

export type FormErrors = Partial<Record<keyof CatalogForm, string>>

export function validateForm(f: CatalogForm, opts: { creating: boolean }): FormErrors {
  const e: FormErrors = {}
  if (opts.creating && !IDENT.test(f.name))
    e.name = "Letters, digits and _ only, at most 64."
  if (f.engine_catalog && !IDENT.test(f.engine_catalog))
    e.engine_catalog = "Letters, digits and _ only, at most 64."
  if (f.kind === "glue") {
    if (f.region && !REGION.test(f.region)) e.region = "Not an AWS region (e.g. ap-northeast-2)."
    if (f.catalog_id && !ACCOUNT.test(f.catalog_id)) e.catalog_id = "A 12-digit AWS account id."
    if (f.role_arn && !ROLE_ARN.test(f.role_arn.trim()))
      e.role_arn = "Like arn:aws:iam::123456789012:role/name."
    if (f.external_id && !f.role_arn.trim()) e.external_id = "Needs a role ARN."
    else if (f.external_id && !EXTERNAL_ID.test(f.external_id.trim()))
      e.external_id = "2-1224 letters, digits or _+=,.@:/-"
    if (f.via_rest) {
      if (!f.region) e.region = "Needed to read through Glue's REST endpoint."
      if (!f.catalog_id) e.catalog_id = "Needed to read through Glue's REST endpoint."
      if (f.is_default) e.via_rest = "The default Glue catalog stays on the Glue API."
    }
  }
  if (f.kind === "iceberg_rest") {
    if (!f.uri.trim()) e.uri = "Required."
    else {
      const p = uriProblem(f.uri.trim())
      if (p) e.uri = p
    }
    if (f.sigv4) {
      if (!f.signing_name) e.signing_name = "Required with SigV4 (glue, s3tables…)."
      else if (!SIGNING_NAME.test(f.signing_name)) e.signing_name = "An AWS service name."
      if (!f.signing_region) e.signing_region = "Required with SigV4."
    }
    if (f.signing_region && !REGION.test(f.signing_region))
      e.signing_region = "Not an AWS region."
  }
  if (f.is_default && !f.enabled) e.enabled = "The default catalog must be enabled."
  return e
}

export function configOf(f: CatalogForm): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {}
  for (const key of KIND_FIELDS[f.kind]) {
    const v = (f as unknown as Record<string, unknown>)[key]
    if (BOOL_FIELDS.has(key)) {
      if (v === true) out[key] = true
    } else if (typeof v === "string" && v.trim() !== "") {
      out[key] = v.trim()
    }
  }
  // SigV4 fields mean nothing without SigV4; keep the stored config honest.
  if (f.kind === "iceberg_rest" && !f.sigv4) {
    delete out.signing_name
    delete out.signing_region
  }
  return out
}

export interface CreatePayload {
  name: string
  kind: CatalogKind
  engine_catalog?: string
  config: Record<string, string | boolean>
  secret?: string
  is_default: boolean
  enabled: boolean
}

export function toCreatePayload(f: CatalogForm): CreatePayload {
  const p: CreatePayload = {
    name: f.name.trim(), kind: f.kind, config: configOf(f),
    is_default: f.is_default, enabled: f.enabled,
  }
  if (f.engine_catalog.trim()) p.engine_catalog = f.engine_catalog.trim()
  if (f.kind === "iceberg_rest" && f.secret) p.secret = f.secret
  return p
}

export type PatchPayload = Partial<{
  engine_catalog: string
  config: Record<string, string | boolean>
  secret: string | null
  is_default: boolean
  enabled: boolean
}>

function sameConfig(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const ka = Object.keys(a).sort(), kb = Object.keys(b).sort()
  return ka.length === kb.length && ka.every((k, i) => k === kb[i] && a[k] === b[k])
}

/** Only what changed. A blank secret leaves the stored one; clearSecret removes it. */
export function toPatchPayload(f: CatalogForm, original: DataCatalog): PatchPayload {
  const p: PatchPayload = {}
  const engine = f.engine_catalog.trim()
  if (engine && engine !== original.engine_catalog) p.engine_catalog = engine
  const cfg = configOf(f)
  if (!sameConfig(cfg, original.config ?? {})) p.config = cfg
  if (f.is_default !== original.is_default) p.is_default = f.is_default
  if (f.enabled !== original.enabled) p.enabled = f.enabled
  if (f.clearSecret) p.secret = null
  else if (f.secret) p.secret = f.secret
  return p
}

export interface TestResult {
  ok: boolean
  namespaces: string[]
  namespace_count: number
  error: string | null
}

export function testSummary(r: TestResult): string {
  if (!r.ok) return r.error || "The catalog did not answer."
  if (r.namespace_count === 0) return "Reachable — no namespaces."
  const more = r.namespace_count > r.namespaces.length
    ? ` (+${r.namespace_count - r.namespaces.length} more)` : ""
  return `Reachable — ${r.namespace_count} namespace${r.namespace_count === 1 ? "" : "s"}: ` +
    r.namespaces.join(", ") + more
}

/** Why an admin cannot do something to this row, or null. Mirrors the 409s. */
export function deleteBlocked(c: DataCatalog): string | null {
  return c.is_default ? "The default catalog cannot be deleted; make another the default first." : null
}

export function disableBlocked(c: DataCatalog): string | null {
  return c.is_default ? "The default catalog cannot be disabled." : null
}

// ── Access: who may use a catalog (GET/PUT /api/catalogs/{name}/grants) ─────────
// No grants: open to everyone with catalog access. One or more: only the granted
// users and roles, plus signed-in admins (backend app/catalog_access.py).

export type GrantKind = "user" | "role"

export interface CatalogGrant {
  kind: GrantKind
  /** A user's id, or a role name. */
  principal: string
  username?: string | null
  email?: string | null
  service_account?: boolean | null
}

/** Someone a grant can name, for the picker: a user or service account by id. */
export interface GrantCandidate {
  id: string
  label: string
  service_account: boolean
}

export const OPEN_ACCESS = "Open to everyone with catalog access"
export const RESTRICT_NOTE =
  "Granting anyone restricts this catalog to the listed callers plus admins."

export function grantKey(g: Pick<CatalogGrant, "kind" | "principal">): string {
  return `${g.kind}:${g.kind === "user" ? g.principal.toLowerCase() : g.principal}`
}

/** The list with `g` added, unless it is already there. */
export function addGrant(list: CatalogGrant[], g: CatalogGrant): CatalogGrant[] {
  const principal = g.principal.trim()
  if (!principal) return list
  const next = { ...g, principal }
  return list.some(x => grantKey(x) === grantKey(next)) ? list : [...list, next]
}

export function removeGrant(list: CatalogGrant[], key: string): CatalogGrant[] {
  return list.filter(g => grantKey(g) !== key)
}

export function grantsPayload(list: CatalogGrant[]): { grants: { kind: GrantKind; principal: string }[] } {
  return { grants: list.map(g => ({ kind: g.kind, principal: g.principal })) }
}

/** Whether the draft differs from what the server holds (order does not matter). */
export function grantsChanged(saved: CatalogGrant[], draft: CatalogGrant[]): boolean {
  const a = saved.map(grantKey).sort(), b = draft.map(grantKey).sort()
  return a.length !== b.length || a.some((k, i) => k !== b[i])
}

/** How a grant reads in the list. A user the server could not name keeps its id. */
export function grantLabel(g: CatalogGrant, candidates: GrantCandidate[] = []): string {
  if (g.kind === "role") return `Role: ${g.principal}`
  const known = candidates.find(c => c.id.toLowerCase() === g.principal.toLowerCase())
  const name = g.username || known?.label || g.principal
  const service = g.service_account ?? known?.service_account ?? false
  return service ? `Service account: ${name}` : `User: ${name}`
}

export function accessSummary(list: CatalogGrant[]): string {
  if (list.length === 0) return OPEN_ACCESS
  const users = list.filter(g => g.kind === "user").length
  const roles = list.length - users
  const parts = [
    users ? `${users} user${users === 1 ? "" : "s"}` : null,
    roles ? `${roles} role${roles === 1 ? "" : "s"}` : null,
  ].filter(Boolean)
  return `Restricted to ${parts.join(" and ")}, plus admins`
}

/** Picker entries from GET /api/service-accounts ({accounts}) and GET /api/auth/users
 *  (a list; service accounts are users too, so an id seen twice keeps its service-
 *  account label). Already-granted ids are left out. */
export function grantCandidates(
  accounts: { id: string; username?: string; display_name?: string | null }[],
  users: { id: string; username?: string | null; display_name?: string | null; email?: string | null }[],
  granted: CatalogGrant[] = [],
): GrantCandidate[] {
  const taken = new Set(granted.filter(g => g.kind === "user").map(g => g.principal.toLowerCase()))
  const out: GrantCandidate[] = []
  const seen = new Set<string>()
  const push = (id: string, label: string, service: boolean) => {
    const k = id.toLowerCase()
    if (!id || seen.has(k) || taken.has(k)) return
    seen.add(k)
    out.push({ id, label, service_account: service })
  }
  for (const a of accounts) push(a.id, a.display_name || a.username || a.id, true)
  for (const u of users) push(u.id, u.display_name || u.username || u.email || u.id, false)
  return out.sort((x, y) => Number(x.service_account) - Number(y.service_account)
    || x.label.localeCompare(y.label))
}

/** A one-line description of where the catalog is, for the list. */
export function locationOf(c: DataCatalog): string {
  const cfg = c.config ?? {}
  if (c.kind === "iceberg_rest") return String(cfg.uri ?? "")
  if (c.kind === "glue") {
    const parts = [cfg.region, cfg.catalog_id ? `account ${cfg.catalog_id}` : null,
      cfg.via_rest ? "via REST" : null].filter(Boolean)
    return parts.join(" · ") || "this account"
  }
  return cfg.warehouse ? `warehouse ${cfg.warehouse}` : ""
}
