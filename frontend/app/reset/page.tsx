"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Loader2, Layers, Lock, Eye, EyeOff, ArrowLeft } from "lucide-react"

export default function ResetPasswordPage() {
  // Read the one-time token from the query string at mount (SSR-guarded). Mirrors the
  // login page's direct URLSearchParams read — no Suspense boundary needed in this build.
  const [token] = useState<string | null>(() =>
    typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("token"))
  const [pw, setPw]             = useState("")
  const [confirm, setConfirm]   = useState("")
  const [showPw, setShowPw]     = useState(false)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!token) { setError("This reset link is invalid or has expired."); return }
    if (pw.length < 6) { setError("Password must be at least 6 characters"); return }
    if (pw !== confirm) { setError("Passwords do not match"); return }
    setLoading(true)
    try {
      const res = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: pw }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail
        throw new Error(detail || "Password reset failed. Please try again.")
      }
      // Success → back to sign in with a note the login page can surface.
      window.location.replace("/login?reset=1")
    } catch (err) {
      setError(err instanceof TypeError
        ? "Unable to reach the server. Check your connection and try again."
        : err instanceof Error ? err.message : "Password reset failed. Please try again.")
      setLoading(false)
    }
  }

  const missingToken = token === null && typeof window !== "undefined"
    && !new URLSearchParams(window.location.search).get("token")

  return (
    <div className="min-h-screen flex">
      {/* ── Left brand panel (matches the sign-in screen) ── */}
      <div className="hidden lg:flex lg:w-[52%] relative flex-col justify-between overflow-hidden"
        style={{ background: "linear-gradient(140deg, #04171c 0%, #071d2e 55%, #0a1430 100%)" }}>
        <div className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: `linear-gradient(rgba(34,211,238,0.8) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(34,211,238,0.8) 1px, transparent 1px)`,
            backgroundSize: "40px 40px",
          }} />
        <div className="absolute top-1/4 left-1/3 w-96 h-96 rounded-full opacity-10 blur-3xl"
          style={{ background: "radial-gradient(circle, #22d3ee 0%, transparent 70%)" }} />
        <div className="relative z-10 flex flex-col justify-between h-full px-12 py-10">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <div className="h-9 w-9 rounded-xl flex items-center justify-center"
                style={{ background: "linear-gradient(120deg, #22d3ee 0%, #60a5fa 55%, #818cf8 100%)" }}>
                <Layers className="h-5 w-5 text-white" />
              </div>
              <span className="text-2xl font-bold tracking-tight text-white">DataPond</span>
            </div>
            <p className="text-sm ml-12" style={{ color: "#7c93a3" }}>Portable AI Data Foundation</p>
          </div>
          <div className="space-y-3">
            <h2 className="text-4xl font-bold text-white leading-tight">
              Set a new password
            </h2>
            <p style={{ color: "#9fb3bf" }} className="text-base leading-relaxed max-w-sm">
              Choose a strong password you don&apos;t use anywhere else. You&apos;ll use it to sign in from now on.
            </p>
          </div>
          <p className="text-xs" style={{ color: "#3f5561" }}>
            © 2026 DataPond · Portable AI Data Foundation
          </p>
        </div>
      </div>

      {/* ── Right panel: reset form ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-background">
        <div className="w-full max-w-sm space-y-8">
          <div className="lg:hidden text-center space-y-1">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-2xl mx-auto mb-2"
              style={{ background: "linear-gradient(120deg, #22d3ee 0%, #60a5fa 55%, #818cf8 100%)" }}>
              <Layers className="h-6 w-6 text-white" />
            </div>
            <h1 className="text-2xl font-bold">DataPond</h1>
            <p className="text-sm text-muted-foreground">Portable AI Data Foundation</p>
          </div>

          <div className="space-y-1">
            <h2 className="text-2xl font-bold tracking-tight">Reset password</h2>
            <p className="text-sm text-muted-foreground">Enter a new password for your account.</p>
          </div>

          {missingToken ? (
            <div className="space-y-6">
              <div role="alert" className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5">
                <Lock className="h-4 w-4 text-destructive shrink-0" />
                <p className="text-sm text-destructive">
                  This reset link is invalid or missing. Request a new one from the sign-in page.
                </p>
              </div>
              <a href="/forgot"
                className="flex items-center justify-center gap-2 text-sm font-medium text-primary hover:underline underline-offset-2">
                <ArrowLeft className="h-4 w-4" />
                Request a new reset link
              </a>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="new-password" className="text-sm font-medium">New password</Label>
                <div className="relative">
                  <Input
                    id="new-password"
                    type={showPw ? "text" : "password"}
                    value={pw}
                    onChange={e => { setPw(e.target.value); setError(null) }}
                    placeholder="Minimum 6 characters"
                    autoComplete="new-password"
                    autoFocus
                    disabled={loading}
                    className="h-10 pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw(v => !v)}
                    aria-label={showPw ? "Hide password" : "Show password"}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirm-password" className="text-sm font-medium">Confirm new password</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirm}
                  onChange={e => { setConfirm(e.target.value); setError(null) }}
                  placeholder="Repeat new password"
                  autoComplete="new-password"
                  disabled={loading}
                  className="h-10"
                />
              </div>

              {error && (
                <div role="alert" aria-live="assertive" className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5">
                  <Lock className="h-4 w-4 text-destructive shrink-0" />
                  <p className="text-sm text-destructive">{error}</p>
                </div>
              )}

              <Button type="submit" className="w-full h-10 font-medium" disabled={loading || !pw || !confirm}>
                {loading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Resetting…</> : "Reset password"}
              </Button>

              <a href="/login"
                className="flex items-center justify-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground">
                <ArrowLeft className="h-4 w-4" />
                Back to sign in
              </a>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
