# OAuth resource-server mode — design (2026-09-28)

## Problem

DataPond accepts two bearer credentials: its own HS256 session JWT and `dp_sk_`
service-account keys. An MCP client that speaks OAuth (the MCP 2026-07-28 spec makes it
the authorization model) cannot connect, and behind an agent gateway every agent
collapses into the one service account whose key the gateway holds. AgentCore Gateway
cannot pass a user's token through to an OpenAPI or MCP target, but it can *exchange*
it (RFC 8693 / Entra OBO) for a token scoped to the target that still names the user.
For DataPond to see that user it must validate access tokens from the customer's IdP.

## Decisions (user-approved)

- **Community core** (`backend/app/oauth_rs.py`), not `/ee`: it is the protocol's
  authorization model, not an upsell. Browser SSO stays in EE.
- **Match existing principals, no JIT.** `(issuer, subject)` must match a `users` row
  (`external_id`, `external_provider` = issuer or NULL, `auth_method` in oidc/service,
  active). A client-credentials token may also match a *service account* linked to its
  `client_id`. No match → 401.
- **Fail closed on scopes.** A token must carry `datapond:<permission>` scopes; the
  caller gets role ∩ scopes (service accounts additionally lose
  `NEVER_FOR_SERVICE_ACCOUNTS`). None → 403 `insufficient_scope`.

## Mechanism

- Config (env, Helm `auth.oauthResourceServer.*`): `OAUTH_RS_ENABLED`,
  `OAUTH_RS_ISSUER` (OIDC/RFC 8414 discovery), `OAUTH_RS_AUDIENCES` (default
  `APP_BASE_URL` and `APP_BASE_URL/api/mcp`), `OAUTH_RS_CLIENT_IDS` (accepted when a
  token has no `aud`, as Cognito's usually do), `OAUTH_RS_SUBJECT_CLAIM` (default `sub`;
  Entra deployments use `oid`), `OAUTH_RS_SCOPE_PREFIX` (default `datapond:`).
- Routing: in `get_current_user`, after the `dp_sk_` branch, a JWT whose header alg is
  RS256/ES256 goes to `oauth_rs.resolve`; HS256 stays DataPond's own session token. An
  external alg is never tried against `SECRET_KEY` and vice versa.
- Validation: JWKS by `kid` (one forced refetch on an unknown kid), RS256/ES256 only,
  `iss`, `exp`/`nbf` with 60 s leeway, audience ∈ `OAUTH_RS_AUDIENCES` or (no `aud` and
  client ∈ `OAUTH_RS_CLIENT_IDS`), `token_use` must not be `id`.
- Challenges: 401 carries `WWW-Authenticate: Bearer resource_metadata="…",
  scope="…"`; a permission refusal for an OAuth caller carries `error="insufficient_scope"`
  and the missing scope.
- Metadata (RFC 9728): `GET /.well-known/oauth-protected-resource` (resource =
  base URL) and `…/api/mcp` (resource = MCP endpoint), served by the backend; the
  ingress routes that prefix to it. 404 when disabled.
- Linking: `PUT/DELETE /api/service-accounts/{id}/oauth-client` binds a client id to a
  service account; `PATCH /api/auth/users/{id}` accepts `external_id` so an admin can
  link a person whose IdP subject differs from what SSO stored (Entra `oid`).
- The token is never forwarded; model calls keep using DataPond's own gateway key.

## Not in scope

DataPond as an authorization server, JIT provisioning, a UI for linking (API first),
opaque-token introspection (Okta org-server tokens are not supported; use a custom
authorization server).
