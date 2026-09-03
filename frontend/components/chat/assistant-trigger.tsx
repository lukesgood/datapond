"use client"

import { useSyncExternalStore } from "react"
import { Bot } from "lucide-react"

import { useHasPermission } from "@/lib/permissions"
import {
  readPanelOpen, serverPanelOpen, subscribeToPanelState, togglePanel,
} from "@/lib/assistant-panel-state"

/** Opens and collapses the assistant panel.
 *
 *  The form is the TOPS project's launcher, measured from
 *  https://tops.csg.fitcloud.co.kr/main.html rather than guessed: a narrow vertical
 *  tab pinned to the right edge at mid-height — 28px wide, `writing-mode: vertical-rl`
 *  so the word runs top to bottom, 12px bold with open letter-spacing, a solid dark
 *  fill with light text, rounded on its left corners only so it reads as attached to
 *  the edge, and a shadow thrown leftward onto the page.
 *
 *  The behaviour is the half worth copying. TOPS does not hide the tab when the panel
 *  opens; it slides it to the panel's outer edge, so one control both opens and
 *  collapses and it never leaves the height your eye last found it at. Only the
 *  horizontal position changes, by exactly the panel's width. That is why this
 *  renders in both states, unlike the two launchers before it — a corner pill and a
 *  top-bar icon — which vanished on open and left closing to a button somewhere else
 *  entirely.
 *
 *  The colour is this product's, not TOPS's. A neutral near-black slab read as foreign
 *  here: the console's signature is the cyan -> blue -> indigo current over an aqua glow,
 *  which the sidebar's logo mark and the login panel already wear. The AI entry point is
 *  exactly the surface that should carry it, so the tab wears it too, with `--dp-aqua`
 *  as its shadow colour thrown leftward onto the page instead of downward.
 *
 *  It wears `.dp-gradient-deep` rather than `.dp-gradient`. The bright stops are for the
 *  logo mark and for glows, which hold no text; white on the lightest of them is 2.4:1
 *  in light and 1.8:1 in dark, and this surface is a mark *and* a word. The deep stops
 *  are the same three hues at 5.4:1 and better, one value for both themes.
 *
 *  It is also bigger than the benchmark — 40px wide against TOPS's 28, 13px semibold,
 *  and an icon above the word — because at TOPS's size against this denser console it
 *  read as a scrollbar artefact rather than a control.
 *
 *  The padding is written as a physical shorthand rather than `py-*` on purpose.
 *  Tailwind's `py-*` is `padding-block`, which is logical: under `vertical-rl` the block
 *  axis runs horizontally, so `py-6` silently became 24px of dead space on the left and
 *  right and none at the ends — and, exceeding the fixed width, widened the tab instead
 *  of lengthening it. `gap` is fine as it is: the flex main axis is the inline axis,
 *  which here runs top to bottom, so it spaces the icon from the word.
 *
 *  `right-[360px]` is the panel's own width from `assistant-panel.tsx`. The panel takes
 *  layout space rather than floating over the page, so at that offset the tab sits
 *  exactly on the panel's left border, the way TOPS's sits on its overlay's edge.
 *
 *  It renders nothing for a caller without `ai:generate`, the same permission the panel
 *  itself checks. A button that opens an empty panel is worse than no button.
 */
export function AssistantTrigger() {
  const canUse = useHasPermission("ai:generate")
  const open = useSyncExternalStore(subscribeToPanelState, readPanelOpen, serverPanelOpen)

  if (!canUse) return null

  return (
    <button
      onClick={togglePanel}
      aria-label={open ? "Collapse assistant" : "Open assistant"}
      aria-expanded={open}
      title="Assistant"
      className={`dp-gradient-deep fixed top-1/2 z-50 flex w-11 -translate-y-1/2
                  items-center justify-center gap-2.5 rounded-l-xl [padding:16px_0]
                  text-[13px] font-semibold tracking-wider text-white
                  shadow-[-6px_0_20px_-6px_var(--dp-aqua)] transition-[right,filter]
                  duration-200 hover:brightness-115 [writing-mode:vertical-rl]
                  ${open ? "right-[360px]" : "right-0"}`}
    >
      <Bot className="h-4 w-4" />
      AI Assistant
    </button>
  )
}
