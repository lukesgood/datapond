"use client"

import { useState } from "react"
import { User, KeyRound, Loader2 } from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { PasskeyManager } from "@/components/passkey-manager"
import { getUser } from "@/lib/auth"
import { useToast } from "@/lib/toast"
import { useCapabilityStrict } from "@/lib/capabilities"

// Per-user account settings — a user's OWN sign-in credentials (password + passkeys),
// separate from the admin/platform Settings page. Available to every logged-in user.
export default function AccountPage() {
  const [user] = useState(() => getUser())
  const webauthnEnabled = useCapabilityStrict("webauthn")
  const { toast } = useToast()
  const [pw, setPw] = useState("")
  const [confirm, setConfirm] = useState("")
  const [busy, setBusy] = useState(false)

  // Inline validity so the user sees why the button is disabled before submitting,
  // instead of only discovering it via a toast after a click.
  const tooShort = pw.length > 0 && pw.length < 6
  const mismatch = confirm.length > 0 && pw !== confirm
  const canSubmit = pw.length >= 6 && pw === confirm

  const changePassword = async () => {
    if (pw.length < 6) { toast("Password must be at least 6 characters", "error"); return }
    if (pw !== confirm) { toast("Passwords do not match", "error"); return }
    setBusy(true)
    try {
      const r = await fetch("/api/auth/change-password", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: pw }),
      })
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
      toast("Password changed", "success")
      setPw(""); setConfirm("")
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to change password", "error")
    }
    setBusy(false)
  }

  return (
    <div className="flex-1 space-y-5 p-8 pt-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">Account</p>
        <h1 className="mt-0.5 text-[23px] font-semibold tracking-tight">Your account</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your own sign-in credentials — password and passkeys.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2"><User className="h-4 w-4" />Profile</CardTitle>
        </CardHeader>
        <CardContent className="text-sm space-y-1.5">
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">Name</span><span className="truncate">{user?.display_name ?? "—"}</span></div>
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">Username</span><span className="font-mono truncate">{user?.username ?? "—"}</span></div>
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">Email</span><span className="truncate">{user?.email ?? "—"}</span></div>
          <div className="flex justify-between gap-4"><span className="text-muted-foreground">Role</span><span className="capitalize">{user?.role ?? "—"}</span></div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2"><KeyRound className="h-4 w-4" />Change password</CardTitle>
          <CardDescription>Set a new password for your own account.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 max-w-sm">
          <div className="space-y-1.5">
            <Label htmlFor="new-password" className="text-xs">New password</Label>
            <Input id="new-password" type="password" autoComplete="new-password" value={pw}
              onChange={e => setPw(e.target.value)} placeholder="At least 6 characters"
              aria-invalid={tooShort} aria-describedby={tooShort ? "new-password-hint" : undefined} />
            {tooShort && (
              <p id="new-password-hint" className="text-[11px] text-[var(--dp-warn)]">
                Use at least 6 characters.
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm-password" className="text-xs">Confirm password</Label>
            <Input id="confirm-password" type="password" autoComplete="new-password" value={confirm}
              onChange={e => setConfirm(e.target.value)}
              onKeyDown={e => e.key === "Enter" && changePassword()}
              aria-invalid={mismatch} aria-describedby={mismatch ? "confirm-password-hint" : undefined} />
            {mismatch && (
              <p id="confirm-password-hint" className="text-[11px] text-destructive">
                Passwords do not match.
              </p>
            )}
          </div>
          <Button onClick={changePassword} disabled={busy || !canSubmit}>
            {busy && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}Update password
          </Button>
        </CardContent>
      </Card>

      {webauthnEnabled && <PasskeyManager />}
    </div>
  )
}
