import { test } from "node:test"
import assert from "node:assert/strict"
import { getProductProfile } from "./product-profile.ts"
import type { Capabilities } from "./capabilities.ts"

// 2.4: the AWS reference runs Trino over the Glue catalog. The catalog backend alone
// says "AWS reference"; `query_engine` is "trino" on every profile and decides nothing.
test("glue catalog with the trino engine still reads as the AWS reference", () => {
  const caps = { _loaded: true, catalog_backend: "glue", query_engine: "trino" } as unknown as Capabilities
  const p = getProductProfile(caps)
  assert.equal(p.id, "aws-managed")
  assert.deepEqual(p.adapters, ["glue", "trino"])
})

test("polaris catalog with the trino engine is not the AWS reference", () => {
  const caps = { _loaded: true, catalog_backend: "polaris", query_engine: "trino" } as unknown as Capabilities
  assert.equal(getProductProfile(caps).id, "portable-core")
})
