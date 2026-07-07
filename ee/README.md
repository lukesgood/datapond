# DataPond Enterprise (`/ee`)

Everything in this repository OUTSIDE this directory is licensed under Apache-2.0
(see the root [LICENSE](../LICENSE)). Code under `/ee` is source-available under the
DataPond Commercial License (see [LICENSE](LICENSE) in this directory) and requires a
valid DataPond Enterprise subscription to use in production.

## Edition boundary

- **Community (Apache-2.0, everything outside `/ee`)**: the full AI data foundation —
  ingestion, vector/RAG, lakehouse integration, LDAP authentication, row-level security,
  AI cost governance, and all current features.
- **Enterprise (`/ee`, commercial)**: future additions — SSO (SAML/OIDC), multi-tenancy,
  AWS Marketplace billing integration, SLA-backed support.

First tenant: SSO (OIDC) — `backend/ee/sso/` (endpoints `/api/auth/oidc/*`). SAML is a
planned follow-up.
