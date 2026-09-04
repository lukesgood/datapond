/** Whether the typed name matches the target the server is expecting.
 *
 *  The server checks this again at approval and refuses a mismatch; this only decides
 *  whether the button is pressable. Both sides forgive the same two things — case, and
 *  the quotes people pick up when copying an identifier — because the point is intent,
 *  not transcription.
 *
 *  Partial names do not count. "customers" is enough for the server to accept that you
 *  *named* crm.customers in conversation, but not to confirm that you mean to change it.
 */
export function canConfirm(typed: string, target: string): boolean {
  // Mirrors normalise() in backend/app/chat/naming.py: strips whitespace and the quote
  // characters `"'` from both ends *exhaustively* — any mixture of them, in any order,
  // not one outer layer. Python's str.strip(chars) treats chars as a set and keeps
  // consuming from each end until it hits a character outside that set; a single regex
  // character class does the same thing in one pass, so " 'crm.customers' " and
  // '  "`crm.customers`"  ' both come out as crm.customers on both sides.
  const clean = (s: string) => (s ?? "").replace(/^[\s"'`]+|[\s"'`]+$/g, "").toLowerCase()
  const wanted = clean(target)
  return wanted.length > 0 && clean(typed) === wanted
}
