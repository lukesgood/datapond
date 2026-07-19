# DataPond Enterprise (`/ee`)

Everything in this repository OUTSIDE this directory is licensed under Apache-2.0
(see the root [LICENSE](../LICENSE)). Code under `/ee` is source-available under the
DataPond Commercial License (see [LICENSE](LICENSE) in this directory) and requires a
valid DataPond Enterprise subscription to use in production.

## Edition boundary

- **Community (Apache-2.0, everything outside `/ee`)**: the Portable Core —
  governed Knowledge/RAG, provider adapters, LDAP authentication, table-policy support,
  AI cost governance, and optional OSS data add-ons.
- **Enterprise (`/ee`, commercial)**: organization-level capabilities including the
  shipped OIDC SSO implementation, plus future centrally managed policy, multi-environment
  operations, Marketplace packaging, and SLA-backed support.

First tenant: SSO (OIDC) — source in `ee/backend/ee/sso/`, served at `/api/auth/oidc/*` by
enterprise-edition backend images. SAML and Marketplace billing are planned follow-ups.
