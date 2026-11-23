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

## Limits

- One dataset with clean names. A schema with cryptic keys (`cust_no`, `ord_cd`) is where
  join guidance should matter, and it was not tested.
- The questions were written by the person who wrote the bindings, so they lean towards
  concepts that exist. The control question (Q20) is a single one.
- The 2026-10-15 metric evaluation also ran three attempts per question through the same
  gateway; if its cache was on, its attempts were not independent either.

## What follows

- The measured value of concepts today is **exact segment conditions**. Encoding segments
  people actually use (tiers, statuses, active flags) is the work that pays.
- Next measurement: the same arms on a source with poorly named keys, to test joins.
- Data gaps found on the way: 상담원 is bound to `agents.id`, a table that does not exist on
  live; 고객 (PII) has only key bindings, so the mask suggestions name id columns and not
  `customers.email` or `full_name`.
