import { test } from "node:test"
import assert from "node:assert/strict"
import {
  configOf, deleteBlocked, disableBlocked, emptyForm, formFromCatalog, locationOf,
  testSummary, toCreatePayload, toPatchPayload, uriProblem, validateForm,
  type DataCatalog,
} from "./data-catalogs.ts"

const REST: DataCatalog = {
  name: "lake", kind: "iceberg_rest", engine_catalog: "lake",
  config: { uri: "https://c.example.com/api/catalog", warehouse: "wh" },
  is_default: false, enabled: true, has_secret: true,
}

test("uri: https anywhere, http only in-cluster or localhost, never with credentials", () => {
  assert.equal(uriProblem("https://c.example.com/api"), null)
  assert.equal(uriProblem("http://polaris.ns.svc.cluster.local:8181/api/catalog"), null)
  assert.equal(uriProblem("http://polaris.ns.svc:8181"), null)
  assert.equal(uriProblem("http://localhost:8181"), null)
  assert.match(uriProblem("http://c.example.com") ?? "", /https/)
  assert.match(uriProblem("https://u:p@c.example.com") ?? "", /credentials/)
  assert.match(uriProblem("not a url") ?? "", /URL/)
})

test("an iceberg_rest form needs a uri, and SigV4 needs a signing name and region", () => {
  const f = emptyForm("iceberg_rest")
  f.name = "lake"
  assert.ok(validateForm(f, { creating: true }).uri)
  f.uri = "https://s3tables.us-east-1.amazonaws.com/iceberg"
  f.sigv4 = true
  const e = validateForm(f, { creating: true })
  assert.ok(e.signing_name && e.signing_region)
  f.signing_name = "s3tables"; f.signing_region = "us-east-1"
  assert.deepEqual(validateForm(f, { creating: true }), {})
})

test("names are bare identifiers; only checked when creating", () => {
  const f = emptyForm("polaris")
  f.name = "bad-name"
  assert.ok(validateForm(f, { creating: true }).name)
  assert.equal(validateForm(f, { creating: false }).name, undefined)
  f.engine_catalog = "a.b"
  assert.ok(validateForm(f, { creating: false }).engine_catalog)
})

test("glue via REST needs region and account, and is not for the default", () => {
  const f = emptyForm("glue")
  f.name = "partner"; f.via_rest = true
  const e = validateForm(f, { creating: true })
  assert.ok(e.region && e.catalog_id)
  f.region = "ap-northeast-2"; f.catalog_id = "123456789012"
  assert.deepEqual(validateForm(f, { creating: true }), {})
  f.is_default = true
  assert.ok(validateForm(f, { creating: true }).via_rest)
  f.catalog_id = "12"
  assert.ok(validateForm(f, { creating: true }).catalog_id)
})

test("the default must be enabled", () => {
  const f = emptyForm("polaris")
  f.name = "x"; f.is_default = true; f.enabled = false
  assert.ok(validateForm(f, { creating: true }).enabled)
})

test("config carries only the kind's keys, trimmed, without empty values", () => {
  const f = emptyForm("iceberg_rest")
  f.uri = " https://c.example.com "; f.region = "us-east-1"; f.signing_name = "glue"
  assert.deepEqual(configOf(f), { uri: "https://c.example.com" })
  f.sigv4 = true; f.signing_region = "us-east-1"
  assert.deepEqual(configOf(f), {
    uri: "https://c.example.com", sigv4: true, signing_name: "glue", signing_region: "us-east-1",
  })
  const g = emptyForm("glue")
  g.region = "us-east-1"; g.uri = "https://ignored"
  assert.deepEqual(configOf(g), { region: "us-east-1" })
})

test("create payload: secret only for iceberg_rest, engine catalog only when given", () => {
  const f = emptyForm("iceberg_rest")
  f.name = "lake"; f.uri = "https://c.example.com"; f.secret = "id:s"
  assert.deepEqual(toCreatePayload(f), {
    name: "lake", kind: "iceberg_rest", config: { uri: "https://c.example.com" },
    is_default: false, enabled: true, secret: "id:s",
  })
  const g = emptyForm("glue")
  g.name = "g"; g.secret = "nope"; g.engine_catalog = "GlueEngine"
  const p = toCreatePayload(g)
  assert.equal(p.secret, undefined)
  assert.equal(p.engine_catalog, "GlueEngine")
})

test("a catalog round-trips through the form unchanged, so an untouched edit sends nothing", () => {
  const f = formFromCatalog(REST)
  assert.equal(f.uri, REST.config.uri)
  assert.equal(f.secret, "")
  assert.deepEqual(toPatchPayload(f, REST), {})
})

test("patch payload carries only what changed; blank secret leaves it, clear removes it", () => {
  const f = formFromCatalog(REST)
  f.enabled = false; f.warehouse = "wh2"
  assert.deepEqual(toPatchPayload(f, REST), {
    enabled: false, config: { uri: REST.config.uri, warehouse: "wh2" },
  })
  const g = formFromCatalog(REST)
  g.clearSecret = true
  assert.deepEqual(toPatchPayload(g, REST), { secret: null })
  const h = formFromCatalog(REST)
  h.secret = "new-token"
  assert.deepEqual(toPatchPayload(h, REST), { secret: "new-token" })
})

test("test summary names the namespaces and how many more there are", () => {
  assert.equal(testSummary({ ok: true, namespaces: ["a", "b"], namespace_count: 25, error: null }),
    "Reachable — 25 namespaces: a, b (+23 more)")
  assert.equal(testSummary({ ok: true, namespaces: [], namespace_count: 0, error: null }),
    "Reachable — no namespaces.")
  assert.equal(testSummary({ ok: false, namespaces: [], namespace_count: 0, error: "401" }), "401")
})

test("the default cannot be deleted or disabled", () => {
  assert.ok(deleteBlocked({ ...REST, is_default: true }))
  assert.ok(disableBlocked({ ...REST, is_default: true }))
  assert.equal(deleteBlocked(REST), null)
})

test("location line per kind", () => {
  assert.equal(locationOf(REST), "https://c.example.com/api/catalog")
  assert.equal(locationOf({ ...REST, kind: "glue",
    config: { region: "us-east-1", catalog_id: "123456789012", via_rest: true } }),
    "us-east-1 · account 123456789012 · via REST")
  assert.equal(locationOf({ ...REST, kind: "glue", config: {} }), "this account")
  assert.equal(locationOf({ ...REST, kind: "polaris", config: { warehouse: "iceberg" } }),
    "warehouse iceberg")
})
