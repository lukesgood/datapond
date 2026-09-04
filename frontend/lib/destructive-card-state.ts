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
  const clean = (s: string) => (s ?? "").trim().replace(/^["'`]+|["'`]+$/g, "").trim().toLowerCase()
  const wanted = clean(target)
  return wanted.length > 0 && clean(typed) === wanted
}
