# Concept bindings: /ai/sql evaluation (2026-11-23)

Does giving the model approved concept bindings (Metrics › Concepts, now Semantic model ›
Concepts) make `/ai/sql` answer more questions correctly? Measured on live, the same 20
questions with and without concepts.

## Setup

- Live AWS reference, build `2.7.0-a28ebe1`, model `litellm:default`, 2026-11-23 ~11:30 KST.
- Data: the sample lake (`iceberg.default`, 23 tables). Context loaded as the server gives
  it: 18 approved metrics, 14 concepts, 34 approved bindings (seeded 2026-11-23).
- Questions: `backend/evals/concept_questions.json` — 20 questions written to need a
  concept: 7 segment + join, 1 segment only, 6 join, 4 using an alias (회원, 구매자, 인보이스,
  제품), 1 control without a join. Each has a reference SQL, checked on live first.
- Arms: `off` — no concepts at all (no concept block, no metric aliases, no join check);
  `on` — as deployed. Interleaved, 3 attempts each, 120 generations.
- **The gateway's response cache was bypassed.** A first run without the bypass returned
  identical SQL for all three attempts (LiteLLM caches identical prompts for an hour), so it
  measured one sample per question. The reported run sends `cache: {"no-cache": true}`;
  questions then produced 2.1 (off) and 1.9 (on) distinct statements on average. Both runs
  gave the same totals.
- Scoring as in the 2026-10-15 metric evaluation: generated and reference SQL executed
  read-only on Trino, row multisets compared, column order ignored, numbers rounded to 2
  decimals, strict otherwise.
- Runner: `backend/evals/concept_eval.py`, run inside the backend container.

## Result

| | off (no concepts) | on (concepts) |
|---|---|---|
| Accurate attempts | 45/60 | **57/60** |
| Questions 3/3 | 15/20 | **19/20** |
| Join errors (wrong key pairs) | 0 | 0 |
| Join-check warnings raised | — | 0 |
| Median generation time | 1.5 s | 1.5 s |

Per question: Q2, Q3, Q7, Q19 went from 0/3 to 3/3; Q14 was 0/3 in both; every other
question was 3/3 in both.

## What made the difference

**Segment values, nothing else.** All twelve gained attempts are the four questions that
name 플래티넘 고객. Without concepts the model writes `tier = 'Platinum'`; the data holds
`platinum`, so the answer is empty or zero. With concepts the segment binding gives
`tier = 'platinum'` and every attempt is right. 활성 고객 (`is_active = true`) and 취소 주문
(`status = 'cancelled'`) were guessed correctly without help.

**Joins: no measurable effect on this data.** Neither arm produced a wrong join in 120
generations, and the join check never fired. The wrong join seen on live earlier the same
day (`customers.id = product_returns.product_id`, the reason for #324) did not reappear.
Without concepts the model sometimes took a longer correct path (returns → order_items →
orders); with concepts it used `product_returns.order_id` directly. The sample schema names
its keys plainly (`customer_id`, `order_id`), which is the easy case for joins.

**Aliases: no effect on SQL.** 회원, 구매자, 인보이스 and 제품 questions were 3/3 in both arms;
the model maps those words to tables on its own. The alias work in step 3 pays in metric
matching instead (`회원 수` → `customer_count`, checked on live), which this evaluation
does not score.

**Q14 is a scoring artifact.** "인보이스 상태별 결제 금액 합계": both arms start from invoices
with a LEFT JOIN and list unpaid statuses with an empty sum; the reference starts from
payments and lists only `paid`. Counted leniently, off is 48/60 and on is 60/60.

## Second run: the same data under legacy-style names

The clean schema is the easy case for joins, so the evaluation was repeated with the same
data shown under names like a legacy ERP (`backend/evals/obf_schema.json`): `orders` is
`iceberg.erp.TB_ORD`, `orders.customer_id` is `BUYER_NO`, `customers.id` is `CST_NO`,
`payments.invoice_id` is `DOC_REF`, `product_returns.product_id` is `RTN_ITEM`. No foreign
key repeats the name of the key it points at.

- Nothing was written to the lake. The model saw only the renamed schema; its SQL was
  translated back by name (sqlglot), then validated and executed on the real tables.
- Concepts were the deployed bindings renamed the same way (22 concepts, 37 bindings after
  the segment additions below). Metrics were left out in both arms, since their definitions
  name the real tables.
- Seven questions had a column named in parentheses; they name the renamed column instead.
- Three attempts first failed on a translation bug (fully qualified column references), not
  on the model; the saved SQL was re-executed after the fix (`--rescore`), no new model calls.

| | off (no concepts) | on (concepts) |
|---|---|---|
| Accurate attempts | 30/60 | **56/60** |
| Questions 3/3 | 10/20 | **17/20** |
| Statements joining keys of two different concepts | 3 | **0** |

Where the 30 failures without concepts came from:

| Cause | Attempts | With concepts |
|---|---|---|
| Segment value guessed: `'PLATINUM'`, `'PT'`, `'P'`, `'CANCELLED'`, `'CANCEL'` (Q2–5, Q17, Q19) | 18 | all right |
| Wrong key pair: `TB_PAY.DOC_REF = TB_ORD.ORD_NO`, an invoice reference read as an order number, plus a guessed tier (Q7) | 3 | all right |
| Longer path through order lines, which gives other numbers on this data (Q9) | 3 | all right (`RTN_ITEM` is bound to 상품) |
| Warehouse id used as the warehouse code, no join to `TB_LOC` (Q8) | 3 | 1/3 right |
| LEFT JOIN from invoices, the reference-strictness case (Q14) | 3 | 1/3 right |

With unhelpful names the gain doubles (+12 → +26 attempts). Segment values are still the
largest part, and now the model guesses legacy-style codes, but joins show up as well: the
wrong key pair in Q7 is exactly what the join check exists for (the check flags all three),
and the bound `RTN_ITEM` key replaced a longer path. Q8 shows the limit: a binding tells the
model which column is a 창고 key, not that "창고 코드" means `LOC_CD` on another table.

## Data changes made with this evaluation

Approved by the owner the same day, made through the console's API functions (audited):

- 상담원's key on `iceberg.default.agents.id` retired: that table does not exist in the lake
  (the first seed wrote it without the table check). Re-bound to
  `src_sample_e_commerce_db.public.agents.id`.
- 고객 gained the attributes `customers.email` and `customers.full_name`, so the PII mask
  suggestions now include the columns that hold personal data, not only id keys.
- Eight segments with values read from the data: 배송 완료 주문 (`status = 'delivered'`),
  골드 고객 (`tier = 'gold'`), 연체 청구서 (`status = 'overdue'`), 결제 완료 청구서
  (`status = 'paid'`), 긴급 문의 (`priority = 'urgent'`), 미해결 문의
  (`status IN ('open', 'pending')`), 환불 완료 반품 (`status = 'refunded'`), 운송 중 배송
  (`status = 'in_transit'`). Live now has 22 concepts and 44 approved bindings.

## Limits

- One dataset. The second run renames it; it is not a real legacy schema with its own
  quirks (composite keys, code tables, mixed languages).
- The questions were written by the person who wrote the bindings, so they lean towards
  concepts that exist. The control question (Q20) is a single one.
- The 2026-10-15 metric evaluation also ran three attempts per question through the same
  gateway; if its cache was on, its attempts were not independent either.

## What follows

- Segment conditions are the largest measured value on both schemas; encoding the segments
  people actually use (tiers, statuses, active flags) is the work that pays first.
- Join guidance pays where names do not help: 0 vs 3 wrong key pairs, and a shorter correct
  path. On a well-named schema it changed nothing measurable.
- A concept cannot say which column of a related table answers a phrase ("창고 코드"). That is
  an attribute binding (창고 → `warehouses.code`), worth adding where questions use it.
