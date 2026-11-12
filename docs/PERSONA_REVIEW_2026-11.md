# Persona review — live console, 2026-11-12

**Scope:** the v7 lakehouse personas walked through the live AWS Single-Node Reference
(release revision 18, chart 2.7.0) in the browser, with the owner's admin session. Admin
sees every page, so the data-engineer, analyst, platform-admin, auditor and AI-developer
flows were walked as admin. Non-admin role views (analyst, viewer, auditor accounts) are
**not** covered yet: they need the owner to sign in as those roles.

Severity: **High** breaks a task or misleads about data; **Medium** a task needs the API
or a workaround; **Low** wording, polish.

## Findings

| # | Persona | Where | Finding | Severity |
|---|---|---|---|---|
| 1 | Data engineer | Sources → Sample E-Commerce DB | `public.api_events` sync fails every run since 11-10: "Column 'payload' changed type from row(...) to varchar". The target was written as a nested `row` by the pre-2.5 path; the Trino sync maps JSON to `varchar` and the widening rules (#252) do not cover JSON → existing `row`. Success rate 70%. | High |
| 2 | Platform admin, analyst | Catalog, Analytics schema tree, `/api/catalogs/health` | The Polaris catalog `polaris_lake` is missing from the table list and the schema tree; health says `401 Unauthorized` from `polaris:8181`. Likely cause: two Polaris replicas each sign tokens with their own key (default token broker), so a token from one is refused by the other. Trino's queries still work (1,200 rows). | High |
| 3 | Data engineer | Sources → table editor, Sync Now | No way to choose the **target catalog** in the console; the table list does not show where a table lands (customers went to Polaris; the page does not say so). API only (`target_catalog`). | Medium |
| 4 | Data engineer, platform admin | Catalog, Settings → Data catalogs | No **catalog export** and no **mirror list/status** in the console. API only. | Medium |
| 5 | Platform admin | Settings → Data catalogs | Source-DB catalogs (`src_*`) offer **Make default** (a live database as the default lake catalog) and **Manage** grants, which the API refuses with 409 since 2.6. | Medium |
| 6 | Auditor | Governance → Access Control | The RLS policy form has schema and table but **no catalog**; with several catalogs a policy cannot say which catalog's table it governs. | Medium |
| 7 | Platform admin | Settings header | Version shows **2.3.0**; the live build is 2.7.0. | Medium |
| 8 | Everyone | Login, forgot/reset password, tab title, sidebar subtitle, product profile, docs summary | v6 copy: "Governed data tool server", "Governed data tools for AI agents", "Governed AI. Without the lock-in.", "Governed RAG Core". | Medium |
| 9 | Analyst | Catalog namespace chips | Three chips read "public (20)" — one per catalog, same label, same (summed) count. | Medium |
| 10 | Analyst | Catalog cards | Live source-DB tables are labelled **Managed**, like lake tables. | Low |
| 11 | Data engineer | Dashboard workflow strip | "Organize — Glue catalog" with two lake catalogs configured. | Low |
| 12 | Everyone | Dashboard | The overview leads with AI tool calls, errors, PII and model spend; nothing about tables, freshness, syncs or queries — the lakehouse persona's first questions. | Medium |
| 13 | Analyst | Table page, Sources | "Open in Query Lab" / "Query in SQL Lab" while the menu says **Analytics**; Sources page is titled **Ingestion**. | Low |
| 14 | Analyst | Metrics | Retired CI/rehearsal metrics ("rehearsal order count …") listed on the live deployment; description is agent-centric. | Low |
| 15 | Auditor | Governance | Opens on the AI **Tool calls** tab; Data Protection shows 1 table scanned for PII out of 40+. | Low |
| 16 | Platform admin | Infrastructure | Polaris reads **Healthy** while DataPond cannot list it (#2); service cards say "Version: Running"; the bar reads "7 / 11 healthy" counting configured adapters as not healthy. | Low |
| 17 | Analyst | Analytics editor | Cmd+Enter ran the previous statement once ("Editor changed since run"); the Run button worked. | Low |

## Worked as expected

- Menu order (Lakehouse → Data Science → AI → Operate) and the dashboard workflow (Connect → Organize → Query → Govern → Add AI).
- A lake ⋈ source-DB join in Analytics: 5 rows in 1.2 s with an automatic chart.
- A query on Polaris through Trino (`polaris_lake.default.customers`, 1,200 rows).
- Table page: preview, column statistics, completeness.
- Connection page: tables, per-table sync settings, sync history with per-table errors, data quality.
- Knowledge collections and search/ask surface.

## Not yet covered

- Non-admin roles (analyst, viewer, auditor accounts) — needs the owner to sign in as each.
- Agents (keys, MCP), AI Gateway, Storage pages — not opened in this pass.
