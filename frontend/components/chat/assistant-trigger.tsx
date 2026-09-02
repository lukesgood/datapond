"use client"

import { useSyncExternalStore } from "react"

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
 *  TOPS hard-codes navy on white. Here the two roles come from `--foreground` and
 *  `--background`, so the tab stays the most contrasting neutral against the page in
 *  either theme instead of going dark-on-dark.
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
      className={`fixed top-1/2 z-50 flex w-7 -translate-y-1/2 items-center justify-center
                  rounded-l-[8px] bg-foreground py-3.5 text-xs font-bold tracking-wider
                  text-background shadow-[-4px_0_12px_rgb(14_28_34_/_0.25)]
                  transition-[right] duration-200 hover:opacity-90
                  [writing-mode:vertical-rl]
                  ${open ? "right-[360px]" : "right-0"}`}
    >
      AI Assistant
    </button>
  )
}
