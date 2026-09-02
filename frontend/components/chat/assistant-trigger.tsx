"use client"

import { useSyncExternalStore } from "react"
import { PanelRightOpen } from "lucide-react"

import { useHasPermission } from "@/lib/permissions"
import {
  readPanelOpen, serverPanelOpen, subscribeToPanelState, togglePanel,
} from "@/lib/assistant-panel-state"

/** Opens the assistant panel, from the top bar.
 *
 *  It lives here rather than inside the panel because of where a person looks for it.
 *  The closed panel used to offer a round button pinned to the middle of the right
 *  edge, while the open panel's close button sits in its header — so opening was a
 *  click at mid-height and closing was a trip to the top of the screen, half a viewport
 *  away. The left sidebar has never had that problem: its `SidebarTrigger` stays in the
 *  top bar whether the sidebar is open or shut.
 *
 *  So this sits at the right end of the same bar, mirroring that trigger. Both states
 *  now put the control in the top-right corner; only the horizontal position shifts,
 *  by the panel's width, because the panel takes layout space rather than floating over
 *  the page.
 *
 *  It renders nothing while the panel is open — the panel's header carries the close
 *  control, which is already in this corner — and nothing at all for a caller without
 *  `ai:generate`, the same permission the panel itself checks. A button that opens an
 *  empty panel is worse than no button.
 */
export function AssistantTrigger() {
  const canUse = useHasPermission("ai:generate")
  const open = useSyncExternalStore(subscribeToPanelState, readPanelOpen, serverPanelOpen)

  if (!canUse || open) return null

  return (
    <button
      onClick={togglePanel}
      aria-label="Open assistant"
      title="Assistant"
      className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground
                 hover:bg-muted hover:text-foreground"
    >
      <PanelRightOpen className="h-4 w-4" />
    </button>
  )
}
