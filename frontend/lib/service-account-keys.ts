// Pure logic for issuing a service-account key. The panel renders these; this file
// is what node --test can reach (same split as collection-members.ts).

export const PREFERRED_DEFAULT_SCOPES = ["knowledge:read", "ai:generate"]
export const DEFAULT_EXPIRY_DAYS = 90
export const EXPIRY_OPTIONS: { label: string; days: number | null }[] = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "1 year", days: 365 },
  { label: "No expiry", days: null },
]

export function choosableScopes(grantable: string[], accountPermissions: string[]): string[] {
  const held = new Set(accountPermissions)
  return [...new Set(grantable.filter(s => held.has(s)))].sort()
}

export function defaultScopes(choosable: string[]): string[] {
  const set = new Set(choosable)
  const preferred = PREFERRED_DEFAULT_SCOPES.filter(s => set.has(s))
  return preferred.length > 0 ? preferred : [...choosable]
}

export function keyRequestBody(name: string, scopes: string[], expiryDays: number | null) {
  const body: { name: string; scopes: string[]; expires_in_days?: number } = { name, scopes }
  if (expiryDays !== null) body.expires_in_days = expiryDays
  return body
}

export function describeKey(k: { scopes: string[]; expires_at: string | null }): string {
  const scopes = k.scopes.length > 0 ? k.scopes.join(", ") : "all role permissions"
  const expiry = k.expires_at ? `expires ${k.expires_at.slice(0, 10)}` : "no expiry"
  return `${scopes} · ${expiry}`
}
