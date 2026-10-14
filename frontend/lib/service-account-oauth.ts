/** The OAuth client row on a service account.
 *
 *  An agent can authenticate with its own client-credentials token from the customer's
 *  IdP instead of a DataPond key, once that client is linked to the account. The server
 *  matches the token's issuer as well as its client, so a link made under an earlier
 *  issuer matches nothing — shown as stale rather than as linked.
 */

export type OAuthMode = { enabled: boolean; issuer: string | null }
export type OAuthClient = { client_id: string; issuer: string | null }

export type OAuthLinkView = {
  state: "off" | "unlinked" | "linked" | "stale"
  clientId: string | null
  canLink: boolean
  canUnlink: boolean
  note?: string
}

const sameIssuer = (a: string | null, b: string | null) =>
  (a ?? "").replace(/\/+$/, "") === (b ?? "").replace(/\/+$/, "")

export function oauthLinkView(mode: OAuthMode | undefined, link: OAuthClient | null | undefined): OAuthLinkView {
  const clientId = link?.client_id ?? null
  if (!mode?.enabled) {
    return {
      state: "off", clientId, canLink: false, canUnlink: clientId !== null,
      note: "OAuth resource-server mode is off on this deployment; agents use DataPond keys.",
    }
  }
  if (!link) return { state: "unlinked", clientId: null, canLink: true, canUnlink: false }
  if (sameIssuer(link.issuer, mode.issuer)) {
    return { state: "linked", clientId, canLink: false, canUnlink: true }
  }
  return {
    state: "stale", clientId, canLink: true, canUnlink: true,
    note: `Linked under ${link.issuer ?? "an unknown issuer"}, not the current issuer — no token matches it. Link it again.`,
  }
}
