"use client"

import { useRef, useEffect } from "react"
import Editor, { OnMount } from "@monaco-editor/react"
import { editor } from "monaco-editor"

/** What the page may do to the editor beyond setting its whole value. */
export interface SqlEditorApi {
  /** Insert text at the cursor (replacing a selection) and focus the editor. */
  insert: (text: string) => void
}

interface SqlEditorProps {
  value: string
  onChange: (value: string) => void
  onExecute: () => void
  apiRef?: { current: SqlEditorApi | null }
}

export function SqlEditor({ value, onChange, onExecute, apiRef }: SqlEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null)
  // Keep a ref so the Monaco keybinding always calls the latest onExecute
  const onExecuteRef = useRef(onExecute)
  useEffect(() => { onExecuteRef.current = onExecute }, [onExecute])

  const handleEditorDidMount: OnMount = (ed) => {
    editorRef.current = ed
    if (apiRef) {
      apiRef.current = {
        insert: (text) => {
          const sel = ed.getSelection()
          if (sel) ed.executeEdits("schema-tree", [{ range: sel, text, forceMoveMarkers: true }])
          ed.focus()
        },
      }
    }
    ed.addCommand(
      2048 | 3, // CtrlCmd + Enter
      () => onExecuteRef.current()
    )
  }

  return (
    <Editor
      height="100%"
      defaultLanguage="sql"
      value={value}
      onChange={(v) => onChange(v || "")}
      onMount={handleEditorDidMount}
      theme="vs-dark"
      options={{
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        automaticLayout: true,
        tabSize: 2,
        wordWrap: "on",
      }}
    />
  )
}
