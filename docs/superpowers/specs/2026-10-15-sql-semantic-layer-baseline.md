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
