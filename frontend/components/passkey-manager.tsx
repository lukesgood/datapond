"use client"

import { useCallback, useEffect, useState } from "react"
import { startRegistration } from "@simplewebauthn/browser"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import { Fingerprint, Plus, Trash2, KeyRound } from "lucide-react"

interface PasskeyCredential {
  id: string
  name: string | null
  created_at: string
  last_used_at: string | null
}

export function PasskeyManager() {
  const [credentials, setCredentials] = useState<PasskeyCredential[]>([])
  const [loading, setLoading] = useState(true)

  const [showAdd, setShowAdd]       = useState(false)
  const [newName, setNewName]       = useState("")
  const [adding, setAdding]         = useState(false)
  const [addError, setAddError]     = useState<string | null>(null)

  const { toast } = useToast()
  const confirmDialog = useConfirm()

  const fetchCredentials = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/auth/webauthn/credentials")
      if (res.ok) setCredentials(await res.json())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchCredentials() }, [fetchCredentials])

  const handleAdd = async () => {
    setAdding(true); setAddError(null)
    try {
      const begin = await fetch("/api/auth/webauthn/register/begin", { method: "POST" })
        .then(r => { if (!r.ok) throw new Error("Failed to start passkey registration"); return r.json() })
      const credential = await startRegistration({ optionsJSON: begin.options })
      const res = await fetch("/api/auth/webauthn/register/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nonce: begin.nonce, credential, name: newName || undefined }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => null)
        throw new Error(d?.detail ?? "Failed to register passkey")
      }
      setShowAdd(false); setNewName("")
      toast("Passkey added", "success")
      fetchCredentials()
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "Failed to add passkey")
    } finally {
      setAdding(false)
    }
  }

  const handleDelete = async (cred: PasskeyCredential) => {
    if (!(await confirmDialog({
      title: "Remove passkey",
      message: `Remove '${cred.name || "Unnamed passkey"}'? You will no longer be able to sign in with it.`,
      destructive: true,
      confirmText: "Remove",
    }))) return
    const res = await fetch(`/api/auth/webauthn/credentials/${cred.id}`, { method: "DELETE" })
    if (res.ok) { toast("Passkey removed", "success"); fetchCredentials() }
    else toast("Failed to remove passkey", "error")
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Fingerprint className="h-4 w-4 text-muted-foreground" />Passkeys
            </CardTitle>
            <CardDescription>Sign in without a password using a device passkey (Face ID, Windows Hello, security key)</CardDescription>
          </div>
          <Button size="sm" onClick={() => { setNewName(""); setAddError(null); setShowAdd(true) }}>
            <Plus className="h-4 w-4 mr-1.5" />Add passkey
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : credentials.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">No passkeys registered yet.</p>
        ) : (
          <div className="divide-y">
            {credentials.map(cred => (
              <div key={cred.id} className="flex items-center gap-3 py-2.5 text-sm">
                <KeyRound className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{cred.name || "Unnamed passkey"}</p>
                  <p className="text-[11px] text-muted-foreground">
                    Added {new Date(cred.created_at).toLocaleDateString()}
                    {cred.last_used_at ? ` · Last used ${new Date(cred.last_used_at).toLocaleDateString()}` : " · Never used"}
                  </p>
                </div>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                  aria-label="Remove passkey" title="Remove passkey" onClick={() => handleDelete(cred)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>

      {/* ── Add Passkey ── */}
      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add a passkey</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-xs text-muted-foreground">
              Your browser will prompt you to use a fingerprint, face scan, PIN, or security key.
            </p>
            <div className="space-y-1.5">
              <Label className="text-xs">Name <span className="text-muted-foreground font-normal">(optional)</span></Label>
              <Input value={newName} onChange={e => setNewName(e.target.value)} placeholder="e.g. MacBook Touch ID" autoFocus />
            </div>
            {addError && <ErrorBox msg={addError} />}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={handleAdd} disabled={adding}>
              {adding ? "Waiting for device…" : "Continue"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
