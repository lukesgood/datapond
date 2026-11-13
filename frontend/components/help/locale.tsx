"use client"

import { useSyncExternalStore } from "react"
import { Languages } from "lucide-react"
import { LOCALE_KEY, initialLocale, pick, type L, type Locale } from "@/lib/help-locale"

// One store for every Help component on the page: a change re-renders them all.
const EVENT = "datapond:help-locale"

function read(): Locale {
  let saved: string | null = null
  try { saved = window.localStorage.getItem(LOCALE_KEY) } catch { /* private window */ }
  return initialLocale(saved, typeof navigator !== "undefined" ? navigator.languages ?? [] : [])
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb)
  window.addEventListener("storage", cb)
  return () => { window.removeEventListener(EVENT, cb); window.removeEventListener("storage", cb) }
}

export function setHelpLocale(locale: Locale) {
  try { window.localStorage.setItem(LOCALE_KEY, locale) } catch { /* not remembered */ }
  window.dispatchEvent(new Event(EVENT))
}

/** The Help language, and `t` to render an `L` in it. Server render is English. */
export function useHelpLocale() {
  const locale = useSyncExternalStore(subscribe, read, () => "en" as Locale)
  return { locale, t: (text: L | string) => pick(text, locale) }
}

/** EN | 한국어 switch, shown on every Help page. */
export function HelpLocaleToggle() {
  const { locale } = useHelpLocale()
  return (
    <div className="inline-flex items-center gap-1 rounded-md border bg-muted/40 p-0.5" role="group" aria-label="Help language">
      <Languages className="ml-1 h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      {(["en", "ko"] as const).map((l) => (
        <button key={l} type="button" onClick={() => setHelpLocale(l)} aria-pressed={locale === l}
          className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
            locale === l ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
          {l === "en" ? "EN" : "한국어"}
        </button>
      ))}
    </div>
  )
}
