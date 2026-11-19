import { test } from "node:test"
import assert from "node:assert/strict"
import { MANUAL, canTestCdc, cdcConnection, createRequest, emptyStream, objectsMade, streamProblem, streamedTables } from "./streaming.ts"

const ready = { success: true, ready: true, tables: ["customers"], checks: [{ key: "wal_level", ok: true, label: "wal_level is logical", detail: null }] }

test("an existing source sends only its id, never credentials", () => {
  const f = { ...emptyStream(), connectionId: "abc", password: "x" }
  assert.deepEqual(cdcConnection(f), { connection_id: "abc", db_schema: "public" })
  assert.equal(canTestCdc(f), true)
  const m = { ...emptyStream(), connectionId: MANUAL, host: "db", database: "shop", user: "etl", password: "p" }
  assert.equal(cdcConnection(m).db_password, "p")
  assert.equal(canTestCdc({ ...m, host: "" }), false)
})

test("streamProblem: create stays off until every check passes", () => {
  const f = { ...emptyStream(), name: "orders_cdc", connectionId: "abc", tables: ["customers"] }
  assert.equal(streamProblem(f, ready), null)
  assert.match(streamProblem({ ...f, name: "bad name" }, ready)!, /Name/)
  assert.match(streamProblem(f, null)!, /Checking/)
  const wal = { ...ready, ready: false, checks: [{ key: "wal_level", ok: false, label: "wal_level is replica", detail: "x" }] }
  assert.match(streamProblem(f, wal)!, /wal_level is replica/)
  assert.match(streamProblem({ ...f, tables: [] }, ready)!, /table/)
  assert.match(streamProblem({ ...emptyStream("kafka"), name: "clicks" }, null)!, /Topic/)
  assert.equal(streamProblem({ ...emptyStream("kafka"), name: "clicks", topic: "t", bootstrap: "k:9092" }, null), null)
})

test("createRequest picks the endpoint and body", () => {
  const c = createRequest({ ...emptyStream(), name: "orders", connectionId: "abc", tables: ["customers"] })
  assert.equal(c.url, "/api/streaming/cdc-pipeline")
  assert.deepEqual(c.body, { pipeline_name: "orders", tables: ["customers"], iceberg_schema: "raw", connection_id: "abc", db_schema: "public" })
  const k = createRequest({ ...emptyStream("kinesis"), name: "s", stream: "st", region: "ap-northeast-2" })
  assert.equal(k.url, "/api/streaming/event-pipeline")
  assert.equal(k.body.stream_name, "st"); assert.equal(k.body.source_type, "kinesis")
})

test("objectsMade and streamedTables", () => {
  assert.deepEqual(objectsMade({ ...emptyStream(), name: "o", tables: ["Customers"] }), ["o_customers_src", "o_customers_mv", "o_customers_sink"])
  assert.deepEqual(objectsMade({ ...emptyStream("kafka"), name: "c" }), ["c_src", "c_mv", "c_sink"])
  assert.deepEqual([...streamedTables(["orders_cdc_orders_src"], ["orders", "customers"])], [["orders", "orders_cdc"]])
})
