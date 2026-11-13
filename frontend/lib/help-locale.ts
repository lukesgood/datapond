/** Language of the Help workspace (Guides and Documentation): English or Korean.
 *
 *  Help text is written as `L` values — `{ en, ko }` — and rendered with `pick`. The
 *  viewer's choice is remembered in localStorage (`datapond.help.locale`); on a first
 *  visit it follows the browser's languages. Only Help is localized: the rest of the
 *  console stays English. Pure functions here; the React hook is in
 *  components/help/locale.tsx.
 */
export type Locale = "en" | "ko"
export type L = { en: string; ko: string }

export const LOCALE_KEY = "datapond.help.locale"

export function parseLocale(v: string | null | undefined): Locale | null {
  return v === "en" || v === "ko" ? v : null
}

export function initialLocale(saved: string | null, languages: readonly string[]): Locale {
  const s = parseLocale(saved)
  if (s) return s
  return languages.some((l) => l.toLowerCase().startsWith("ko")) ? "ko" : "en"
}

export function pick(text: L | string, locale: Locale): string {
  if (typeof text === "string") return text
  return (locale === "ko" ? text.ko : text.en) || text.en
}
