/** Which OAuth row a service account shows (./service-account-oauth.ts). */
import assert from "node:assert/strict"
import { test } from "node:test"
import { oauthLinkView } from "./service-account-oauth.ts"

const ISSUER = "https://idp.example.com/oauth2/default"
const ON = { enabled: true, issuer: ISSUER }
const OFF = { enabled: false, issuer: null }

test("with the mode off there is nothing to link, and it says why", () => {
  const v = oauthLinkView(OFF, null)
  assert.equal(v.state, "off")
  assert.equal(v.canLink, false)
})

test("a link kept from when the mode was on is still shown, and can be removed", () => {
  const v = oauthLinkView(OFF, { client_id: "agent-client", issuer: ISSUER })
  assert.equal(v.state, "off")
  assert.equal(v.clientId, "agent-client")
  assert.equal(v.canUnlink, true)
})

test("an unlinked account under a live mode offers to link", () => {
  const v = oauthLinkView(ON, null)
  assert.equal(v.state, "unlinked")
  assert.equal(v.canLink, true)
  assert.equal(v.canUnlink, false)
})

test("a link under the current issuer is live", () => {
  const v = oauthLinkView(ON, { client_id: "agent-client", issuer: ISSUER })
  assert.equal(v.state, "linked")
  assert.equal(v.clientId, "agent-client")
  assert.equal(v.canUnlink, true)
})

test("a trailing slash on either issuer is not a different issuer", () => {
  assert.equal(oauthLinkView(ON, { client_id: "c", issuer: `${ISSUER}/` }).state, "linked")
})

test("a link made under another issuer matches no token, so it is stale and can be relinked", () => {
  const v = oauthLinkView(ON, { client_id: "agent-client", issuer: "https://old-idp.example.com" })
  assert.equal(v.state, "stale")
  assert.equal(v.canLink, true)
  assert.equal(v.canUnlink, true)
  assert.match(v.note ?? "", /old-idp\.example\.com/)
})

test("an older server that sends no OAuth fields reads as off", () => {
  assert.equal(oauthLinkView(undefined, undefined).state, "off")
})
