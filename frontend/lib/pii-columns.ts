/** Columns whose name says they probably hold personal data, so the setup page can
 *  pre-fill "Mask" before the first sync. A guess from the name only — the person sees
 *  and edits it — matched on whole name parts so `hotel` is not a phone (`tel`) and
 *  `company` not a card number (`pan`). Same families as app/api/governance.py
 *  PII_COLUMN_PATTERNS, plus the Korean names the first segment uses. */
const PARTS = new Set([
  "email", "mail", "phone", "mobile", "tel", "cell", "fax",
  "ssn", "rrn", "jumin", "passport", "card", "pan", "iban", "account",
  "name", "fullname", "firstname", "lastname", "address", "addr", "street", "zip", "zipcode", "postal", "postcode",
  "dob", "birth", "birthday", "birthdate", "ip",
])
const PAIRS = [["first", "name"], ["last", "name"], ["full", "name"], ["card", "number"], ["social", "security"], ["birth", "date"]]
// Names that contain a part above but are not about a person.
const NOT_PERSONAL = new Set(["table_name", "file_name", "filename", "product_name", "category_name", "company_name",
  "brand_name", "account_type", "account_id", "card_type", "ip_version", "name_en", "host_name", "hostname", "db_name"])
const KOREAN = ["주민", "전화", "휴대", "핸드폰", "이메일", "메일", "주소", "성명", "이름", "생년", "생일", "계좌", "카드번호", "여권"]

export function likelyPii(column: string): boolean {
  const lower = column.toLowerCase()
  if (NOT_PERSONAL.has(lower)) return false
  if (KOREAN.some(k => column.includes(k))) return true
  const parts = lower.split(/[^a-z0-9]+|(?<=[a-z])(?=[0-9])/).filter(Boolean)
  if (parts.some(p => PARTS.has(p))) return true
  return PAIRS.some(([a, b]) => parts.includes(a) && parts.includes(b))
}

export function suggestedMasks(columns: { name: string }[]): string[] {
  return columns.map(c => c.name).filter(likelyPii)
}
