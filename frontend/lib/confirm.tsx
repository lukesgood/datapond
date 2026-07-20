"use client"

// Promise-based styled confirm dialog — replaces native window.confirm() so
// destructive actions get a consistent, accessible, on-brand prompt.
// Usage:  const confirm = useConfirm()
//         if (!(await confirm({ title, message, destructive: true }))) return
import { createContext, useContext, useRef, useState, useCallback, ReactNode } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { AlertTriangle } from "lucide-react"

type ConfirmOpts = {
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
  destructive?: boolean
}
type ConfirmFn = (opts: ConfirmOpts) => Promise<boolean>

const ConfirmContext = createContext<ConfirmFn | undefined>(undefined)

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [opts, setOpts] = useState<ConfirmOpts>({})
  const resolver = useRef<((v: boolean) => void) | null>(null)

  const confirm = useCallback<ConfirmFn>((o) => {
    setOpts(o)
    setOpen(true)
    return new Promise<boolean>((res) => { resolver.current = res })
  }, [])

  const done = (v: boolean) => {
    setOpen(false)
    resolver.current?.(v)
    resolver.current = null
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={open} onOpenChange={(o) => { if (!o) done(false) }}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              {opts.destructive && <AlertTriangle className="h-4 w-4 text-destructive" />}
              {opts.title || "Confirm"}
            </DialogTitle>
          </DialogHeader>
          {opts.message && (
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{opts.message}</p>
          )}
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => done(false)}>
              {opts.cancelText || "Cancel"}
            </Button>
            <Button size="sm" variant={opts.destructive ? "destructive" : "default"} onClick={() => done(true)}>
              {opts.confirmText || "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  )
}

export function useConfirm() {
  const c = useContext(ConfirmContext)
  if (!c) throw new Error("useConfirm must be used within ConfirmProvider")
  return c
}
