"use client"

import { useMemo } from "react"
import { useRouter } from "next/navigation"
import ReactFlow, { Background, Controls, MarkerType, Position, type Edge, type Node } from "reactflow"
import "reactflow/dist/style.css"
import type { Binding, Concept } from "@/lib/concepts"
import { conceptHref, ontologyGraph, ontologyLayout } from "@/lib/concept-map"

/** Concepts as nodes (Data Map step 4). A solid line joins two concepts when one table
 *  holds keys of both, labelled with that table; a dashed arrow points from a concept to
 *  a narrower one. Segments sit beside their parent as small pills. Nothing here is
 *  drawn by hand: every line comes from approved bindings or a concept's parent.
 *
 *  With `centre`, only that concept and the ones one line away. Click a concept to open
 *  its page. */
export function OntologyMap({ concepts, bindings, centre = null, height = 420 }: {
  concepts: Concept[]; bindings: Binding[]; centre?: string | null; height?: number
}) {
  const router = useRouter()
  const { nodes, edges, pos } = useMemo(() => ontologyLayout(ontologyGraph(concepts, bindings), centre), [concepts, bindings, centre])

  if (nodes.length === 0) return <p className="rounded-md border p-4 text-xs text-muted-foreground">No concepts yet.</p>
  if (centre && nodes.length === 1) {
    return <p className="rounded-md border p-4 text-xs text-muted-foreground">No other concept shares a table with this one, and it has no narrower concept.</p>
  }

  const flowNodes: Node[] = nodes.map(n => {
    const isCentre = n.name === centre
    return {
      id: n.name, position: pos[n.name] ?? { x: 0, y: 0 },
      sourcePosition: Position.Right, targetPosition: Position.Left,
      ariaLabel: `${n.name}${n.segment ? ", segment" : ""}${n.pii ? ", personal data" : ""}. Open its page.`,
      data: {
        label: (
          <span className={n.segment ? "text-2xs" : "text-xs font-medium"}>
            {n.name}{n.pii ? " · PII" : ""}
            {!n.segment && n.tables === 0 && <span className="block text-2xs font-normal text-muted-foreground">bound nowhere</span>}
          </span>
        ),
      },
      style: {
        width: n.segment ? 120 : 140, borderRadius: 999, padding: n.segment ? "2px 8px" : "6px 10px", cursor: "pointer",
        background: n.segment ? "var(--card)" : "var(--muted)", color: "var(--foreground)",
        border: isCentre ? "2px solid var(--primary)"
          : n.segment ? "1px dashed var(--border)"
          : n.tables === 0 ? "1px dashed var(--muted-foreground)" : "1px solid var(--primary)",
      },
    }
  })
  const flowEdges: Edge[] = edges.map(e => e.kind === "shares" ? {
    id: `s:${e.from}|${e.to}`, source: e.from, target: e.to, type: "straight",
    label: e.via.length > 2 ? `${e.via.slice(0, 2).join(", ")} +${e.via.length - 2}` : e.via.join(", "),
    labelStyle: { fontSize: 9 }, labelBgPadding: [3, 1] as [number, number], labelBgStyle: { fill: "var(--card)" },
  } : {
    id: `n:${e.from}|${e.to}`, source: e.from, target: e.to, type: "straight",
    style: { strokeDasharray: "4 3" }, markerEnd: { type: MarkerType.ArrowClosed },
  })

  return (
    <div className="space-y-1.5">
      <div className="rounded-md border" style={{ height }}>
        <ReactFlow nodes={flowNodes} edges={flowEdges} fitView proOptions={{ hideAttribution: true }}
                   nodesDraggable={false} nodesConnectable={false} minZoom={0.3}
                   onNodeClick={(_e, n) => { if (n.id !== centre) router.push(conceptHref(n.id)) }}>
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <p className="text-2xs text-muted-foreground">
        Solid line: one table holds keys of both (labelled with the table). Dashed arrow: a narrower concept.
        Small pills are segments. A dashed outline is a concept bound to no column yet.
      </p>
    </div>
  )
}
