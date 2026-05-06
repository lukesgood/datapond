"use client"

import { useRef, useEffect } from "react"
import Editor, { OnMount } from "@monaco-editor/react"
import { editor } from "monaco-editor"

interface SqlEditorProps {
  value: string
  onChange: (value: string) => void
  onExecute: () => void
}

export function SqlEditor({ value, onChange, onExecute }: SqlEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null)
  // Keep a ref so the Monaco keybinding always calls the latest onExecute
  const onExecuteRef = useRef(onExecute)
  useEffect(() => { onExecuteRef.current = onExecute }, [onExecute])

  const handleEditorDidMount: OnMount = (ed) => {
    editorRef.current = ed
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
