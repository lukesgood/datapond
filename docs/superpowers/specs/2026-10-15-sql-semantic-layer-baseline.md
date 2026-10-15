> Pre-implementation measurement (Task 0), recorded before any semantic-layer code existed.

# /ai/sql baseline (pre-semantic-layer)

- Date: 2026-10-15 (KST ~15:00-15:30), live node i-0bbf886f0728f3e6e, build 2.3.0-6a4e555
- Model: /ai/sql reports provider `litellm:default` (no concrete model name exposed in response)
- Data: 23 Iceberg tables in Glue `default`; orders span 2026-04-21..2026-08-18, so explicit 2026 periods used (no relative dates). Generated SQL is validated, then executed via /api/queries/execute with save_history=false.
- Compare: row multisets, column order ignored, numbers rounded to 2 decimals, strict (extra/renamed value formats count as wrong).

## Totals

- Accurate attempts: **52/60**
- Questions 3/3 accurate: **17/20**
- Questions 3/3 agreeing result sets: **19/20**
- Attempts with no SQL: 0; failed execution: 0
- All 3 misses classes: Q4 (format-only), Q9 (ambiguous wording), Q13 (tie nondeterminism). Lenient reading would put accuracy at 55/60 (Q4 counted correct), with Q9 and Q13 questionable.

## Per question

| # | Question | Reference SQL | Attempts | Agree | Notes |
|---|---|---|---|---|---|
| 1 | 2026년 7월 주문은 총 몇 건인가요? | `SELECT count(*) FROM orders WHERE year(ordered_at)=2026 AND month(ordered_at)=7` | ✓✓✓ | yes |  |
| 2 | 2026년 7월 취소된 주문을 제외한 총 매출액은 얼마인가요? | `SELECT sum(total_amount) FROM orders WHERE year(ordered_at)=2026 AND month(ordered_at)=7 AND status<>'cancelled'` | ✓✓✓ | yes |  |
| 3 | 2026년 6월 채널별 주문 건수를 알려주세요. | `SELECT channel, count(*) FROM orders WHERE year(ordered_at)=2026 AND month(ordered_at)=6 GROUP BY channel` | ✓✓✓ | yes |  |
| 4 | 2026년 5월부터 8월까지 월별 주문 건수를 보여주세요. | `SELECT month(ordered_at), count(*) FROM orders WHERE year(ordered_at)=2026 AND month(ordered_at) BETWEEN 5 AND 8 GROUP BY 1` | ✗✗✗ | yes | Semantically right (monthly counts match) but model returns DATE_TRUNC timestamps instead of month numbers; strict compare marks wrong (format-only). |
| 5 | 배송 완료(delivered) 상태 주문의 평균 주문 금액은 얼마인가요? | `SELECT avg(total_amount) FROM orders WHERE status='delivered'` | ✓✓✓ | yes |  |
| 6 | 국가별 고객 수를 알려주세요. | `SELECT country, count(*) FROM customers GROUP BY country` | ✓✓✓ | yes |  |
| 7 | 등급(tier)별 활성 고객 수는 몇 명인가요? | `SELECT tier, count(*) FROM customers WHERE is_active GROUP BY tier` | ✓✓✓ | yes |  |
| 8 | 상품 카테고리별 평균 판매가를 알려주세요. | `SELECT category, avg(price) FROM products GROUP BY category` | ✓✓✓ | yes |  |
| 9 | 활성 상품 기준으로 카테고리별 재고 수량 합계를 알려주세요. | `SELECT category, sum(stock_qty) FROM products WHERE is_active GROUP BY category` | ✗✗✗ | yes | Interpretation: model summed inventory.on_hand via join; reference uses products.stock_qty. Question ambiguous (my wording). |
| 10 | 2026년 7월에 발행된 청구서의 금액 합계는 얼마인가요? | `SELECT sum(amount) FROM invoices WHERE year(issued_on)=2026 AND month(issued_on)=7` | ✓✓✓ | yes |  |
| 11 | 청구서 상태별 건수와 금액 합계를 보여주세요. | `SELECT status, count(*), sum(amount) FROM invoices GROUP BY status` | ✓✓✓ | yes |  |
| 12 | 결제 수단별 결제 금액 합계를 알려주세요. | `SELECT method, sum(amount) FROM payments GROUP BY method` | ✓✓✓ | yes |  |
| 13 | 주문 건수가 가장 많은 고객 상위 5명의 고객 ID와 주문 건수를 알려주세요. | `SELECT customer_id, count(*) c FROM orders GROUP BY customer_id ORDER BY c DESC, customer_id LIMIT 5` | ✗✗✓ | no | Tie at 5th place (13 orders for ids 3, 10, 18, ...); model has no tiebreak so result varies / differs from reference tiebreak. Question ambiguous. |
| 14 | 취소되지 않은 주문 기준으로 상품 카테고리별 매출(수량 x 단가) 합계를 알려주세요. | `SELECT p.category, sum(oi.quantity*oi.unit_price) FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id WHERE o.status<>'cancelled' GROUP BY p.category` | ✓✓✓ | yes |  |
| 15 | 2026년 7월에 배송이 완료된(delivered_at 기준) 배송 건수를 운송사별로 알려주세요. | `SELECT carrier, count(*) FROM shipments WHERE year(delivered_at)=2026 AND month(delivered_at)=7 GROUP BY carrier` | ✓✓✓ | yes |  |
| 16 | 우선순위별 고객지원 티켓 건수를 알려주세요. | `SELECT priority, count(*) FROM support_tickets GROUP BY priority` | ✓✓✓ | yes |  |
| 17 | 반품 상태별 환불 금액 합계를 알려주세요. | `SELECT status, sum(refund_amount) FROM product_returns GROUP BY status` | ✓✓✓ | yes |  |
| 18 | API 이벤트 중 상태 코드가 500 이상인 요청은 몇 건인가요? | `SELECT count(*) FROM api_events WHERE status_code>=500` | ✓✓✓ | yes |  |
| 19 | 창고 코드별 총 재고 수량(on_hand)을 알려주세요. | `SELECT w.code, sum(i.on_hand) FROM inventory i JOIN warehouses w ON w.id=i.warehouse_id GROUP BY w.code` | ✓✓✓ | yes |  |
| 20 | 2026년 5월 주문의 평균 할인액은 얼마인가요? | `SELECT avg(discount) FROM orders WHERE year(ordered_at)=2026 AND month(ordered_at)=5` | ✓✓✓ | yes |  |

---

# After-measurement (post-deploy, live 2.3.0-5d79ca9)

- Date: 2026-10-15 KST ~16:37-16:55, live node i-0bbf886f0728f3e6e, in-pod admin session against localhost:8000.
- Same 20 questions, reference SQL and scoring as the baseline (row multisets, column order ignored, numbers rounded to 2 dp, strict).
- (a) = /api/ai/sql with 15 approved definitions as context (server-side, automatic), SQL then executed via /api/queries/execute. (b) = POST /api/semantic/metrics/{name}/query, 3 calls per question.

## Totals

| | Baseline | (a) /ai/sql + definitions | (b) metric path |
|---|---|---|---|
| Accurate attempts | 52/60 | **55/60** | **51/54** (of the 18 covered questions) |
| Questions 3/3 accurate | 17/20 | **18/20** | 17/18 covered |
| Questions 3/3 agreeing | 19/20 | **19/20** | 18/18 (deterministic) |
| Coverage | n/a | 20/20 answered | **18/20** (Q13, Q14 not coverable) |

Q4 is format-only in both: counts match per month, but the month grain returns a timestamp (`2026-05-01T00:00:00+00:00`) where the reference has a month number. Lenient (Q4 correct): (a) 58/60, (b) 54/54.
(a) delta vs baseline: Q9 flipped ✗✗✗ to ✓✓✓ (the `stock_qty` definition removed the products.stock_qty vs inventory.on_hand ambiguity). Q4 and Q13 unchanged (Q13: still no tiebreak, ✗✗✓; not a metric question).
(b) is deterministic: 3 identical results per question; 0 HTTP errors across 18 questions x 3.

## Per question

| # | Question | Baseline | (a) attempts | (b) attempts | metric used | suggested_metric hit | notes |
|---|---|---|---|---|---|---|---|
| 1 | 2026년 7월 주문은 총 몇 건인가요? | ✓✓✓ | ✓✓✓ | ✓✓✓ | order_count | MISS (null) | suggest returned null although metric is in metrics_provided top and name matches |
| 2 | 2026년 7월 취소된 주문을 제외한 총 매출액은 얼마인가요? | ✓✓✓ | ✓✓✓ | ✓✓✓ | revenue | yes |  |
| 3 | 2026년 6월 채널별 주문 건수를 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | order_count | yes |  |
| 4 | 2026년 5월부터 8월까지 월별 주문 건수를 보여주세요. | ✗✗✗ | ✗✗✗ | ✗✗✗ | order_count | yes | both paths: timestamp per month vs month number (format-only) |
| 5 | 배송 완료(delivered) 상태 주문의 평균 주문 금액은 얼마인가요? | ✓✓✓ | ✓✓✓ | ✓✓✓ | avg_order_amount | yes | (b) where status=delivered, period 2026-01-01..2026-12-31 |
| 6 | 국가별 고객 수를 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | customer_count | yes |  |
| 7 | 등급(tier)별 활성 고객 수는 몇 명인가요? | ✓✓✓ | ✓✓✓ | ✓✓✓ | customer_count | yes |  |
| 8 | 상품 카테고리별 평균 판매가를 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | avg_price | yes |  |
| 9 | 활성 상품 기준으로 카테고리별 재고 수량 합계를 알려주세요. | ✗✗✗ | ✓✓✓ | ✓✓✓ | stock_qty | yes | (a) fixed by definition; (b) stock_qty where is_active=true |
| 10 | 2026년 7월에 발행된 청구서의 금액 합계는 얼마인가요? | ✓✓✓ | ✓✓✓ | ✓✓✓ | invoice_amount | MISS (null) | suggest returned null although metric is in metrics_provided top and name matches |
| 11 | 청구서 상태별 건수와 금액 합계를 보여주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | invoice_count+invoice_amount | MISS (null) | (b) two calls merged (invoice_count + invoice_amount by status); suggest returned null although metric is in metrics_provided top and name matches |
| 12 | 결제 수단별 결제 금액 합계를 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | payment_amount | yes |  |
| 13 | 주문 건수가 가장 많은 고객 상위 5명의 고객 ID와 주문 건수를 알려주세요. | ✗✗✓ | ✗✗✓ | n/a | - | n/a (not coverable) — suggested order_count | (b) not coverable: top-N ranking/ORDER BY LIMIT is not expressible; (a) still tie-nondeterministic |
| 14 | 취소되지 않은 주문 기준으로 상품 카테고리별 매출(수량 x 단가) 합계를 알려주세요. | ✓✓✓ | ✓✓✓ | n/a | - | n/a (not coverable) — suggested revenue | (b) not coverable: two-hop join (order_items to orders to products) with filter on joined table; suggest wrongly offered revenue |
| 15 | 2026년 7월에 배송이 완료된(delivered_at 기준) 배송 건수를 운송사별로 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | delivered_shipments | yes |  |
| 16 | 우선순위별 고객지원 티켓 건수를 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | ticket_count | yes |  |
| 17 | 반품 상태별 환불 금액 합계를 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | refund_amount | yes |  |
| 18 | API 이벤트 중 상태 코드가 500 이상인 요청은 몇 건인가요? | ✓✓✓ | ✓✓✓ | ✓✓✓ | api_error_count | yes |  |
| 19 | 창고 코드별 총 재고 수량(on_hand)을 알려주세요. | ✓✓✓ | ✓✓✓ | ✓✓✓ | on_hand_qty | yes |  |
| 20 | 2026년 5월 주문의 평균 할인액은 얼마인가요? | ✓✓✓ | ✓✓✓ | ✓✓✓ | avg_discount | yes |  |

## Definitions created (all approved v1, left in place)

Join (id 1): default.inventory.warehouse_id -> default.warehouses.id (manual, approved).

order_count, revenue (status <> 'cancelled'), avg_order_amount, avg_discount, customer_count, avg_price, stock_qty, invoice_amount, invoice_count, payment_amount, delivered_shipments, ticket_count, refund_amount, api_error_count (status_code >= 500), on_hand_qty (dimension warehouse_code = warehouses.code via join 1). Exactly the brief's set (15 metrics), no column adaptations were needed. All POST create = 201 and approve = 200 on the first try.

## Audit + MCP

- GET /api/audit/tool-calls?limit=20: rows with tool `metric.query`, resource_kind `metric`, outcome ok, citation_sources `["metric:<name>@v1"]` (e.g. avg_discount, avg_price) and hit_count = row count. Confirmed.
- POST /api/mcp tools/list returned 28 tools including metric_list, metric_describe, metric_query. (CLAUDE.md/commit message say 29 actions; the listing for an admin session had 28 names.)
- tools/call metric_query (order_count by channel, 2026-06) returned rows [[direct,2],[mobile,423],[partner,398],[web,809]] plus `citation` (metric, version, approved_by/at, sql, period, rls_applied=false, pii_masked=0), wrapped as untrusted content.

## Defects / observations

1. No 4xx on any create/approve/query call.
2. `suggested_metric` is null for Q1 (order_count), Q10 (invoice_amount) and Q11 (invoice_count/amount) although the right metric heads `metrics_provided` (Q2, Q18, Q20, which are similar no-`by` questions, do get a suggestion). Likely the matcher keys on the label/synonym wording ('주문 수' vs '주문은 ... 몇 건', '청구서 금액' vs '발행된 청구서의 금액 합계'); cause not investigated. Metric choice still reached 20/20 via the context block.
3. `suggested_metric` gives a plausible-looking but wrong suggestion for non-coverable questions: Q13 -> order_count, Q14 -> revenue (revenue dims are only [channel]; question needs category via a two-hop join). A client that auto-follows suggestions would return a wrong answer for Q14.
4. Q4 grain output is a timestamp per month, not a month number (format-only; same as /ai/sql).
5. Not coverable by metrics: top-N ranking (Q13) and filters/dimensions across a two-hop join (Q14). (a) still answers Q14 correctly via free SQL.
6. Self-inflicted, not a product defect: I launched 5 concurrent in-pod Python processes via SSM and one backend pod (backend-666d5df5c-drr2r) restarted once (exit 137, likely OOM from my processes) at ~16:41; it recovered (1 restart, Running). Subsequent runs were sequential or 2 concurrent. Worth knowing: an in-pod harness per run loads the full app (~300Mi+ each).
7. SSM stdout is capped (~24 KB): the first (b) run lost output; reran with trimmed output. No effect on results.
8. Data note: June channel 'direct' has 2 orders, a tie/oddity irrelevant to correctness.

## Reading (controller notes)
- (b) metric path: the only misses are Q4's three attempts, and those are format-only — the month grain returns a timestamp, while the reference returns a month number. On content, all 18 covered questions are right on all 3 attempts. Q13 (top-N ranking) and Q14 (two-hop join with a filter on a joined table) are out of v1 scope.
- (a) the gain comes from Q9: the `stock_qty` definition settled the ambiguity, and the wrong answer was not repeated. That is what definitions as context are for.
- `suggested_metric` uses verbatim label/synonym matching, which is stricter than the questions' wording. Examples: "주문은 총 몇 건" vs "주문 건수", and "청구서의 금액 합계" vs "청구서 금액 합계". It also matches a word without understanding scope ("매출" in Q14 suggests `revenue`). Follow-up: token-level matching, plus a note that the suggestion is a hint.
- `tools/list` on live shows 28 of the 29 READ tools. The one hidden is `pipelines.recent_runs`, whose `pipelines` capability is off on the AWS single-node profile. This is per-deployment capability gating, as designed.
- During measurement the backend pod restarted once (exit 137). Five in-pod measurement scripts were running at once, so the measurement load caused it, not product traffic. It recovered without intervention.

---

# Backend memory check (2026-10-16, live 2.3.0-5d79ca9)

Why: the backend pod restarted once (exit 137) during the after-measurement.

- Limits (live = chart): 2 replicas, requests 500m / 512Mi, limits 1 CPU / 1Gi. The node had 11.9 GiB available.
- Idle after the 07:30 start: 324Mi and 332Mi; restarts 0.
- Load, in-pod against one replica's uvicorn (PID 1 VmHWM):
  - 20 concurrent requests (12 `metric_query`, 4 `/ai/sql`, 4 `SELECT ... LIMIT 1000`): all 200 in 9.3 s; peak 542 MiB.
  - Then 40 concurrent requests (24 / 8 / 8): all 200 in 13.4 s; peak 560 MiB.
  - The process keeps that memory after the load (Python allocator), so the steady state after traffic is about 550 MiB.
- Reading: product traffic at 40 concurrent requests uses about 55% of the 1Gi limit.
  - The restart came from the measurement method. Each in-pod Python harness loads the whole app, about 150 to 300 MiB, inside the backend container's cgroup. Five harnesses plus the server went past 1Gi.
- Rule: run in-pod harnesses one at a time, or as a separate Job pod. No chart change.
