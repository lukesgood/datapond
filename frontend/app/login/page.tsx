"use client"

import { useState, useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { login, isAuthenticated, clearAuth, responseErrorMessage, saveAuth, type AuthUser } from "@/lib/auth"
import { Loader2, Eye, EyeOff, ShieldCheck, Layers, Zap, Lock, AlertTriangle, WifiOff, Fingerprint } from "lucide-react"
import { startAuthentication } from "@simplewebauthn/browser"

const FEATURES = [
  {
    icon: ShieldCheck,
    title: "Governed RAG Core",
    desc: "Ingest, chunk, embed, retrieve, rerank, and answer with collection access controls, PII masking, citations, and spend attribution.",
  },
  {
    icon: Layers,
    title: "Open by Contract",
    desc: "S3-compatible objects, PostgreSQL + pgvector, and LiteLLM keep storage, vectors, and model providers replaceable.",
  },
  {
    icon: Zap,
    title: "AWS-Ready, Not AWS-Locked",
    desc: "Use the AWS reference adapters or run the Portable Core with self-hosted OSS add-ons in infrastructure you control.",
  },
]

export default function LoginPage() {
  const usernameRef = useRef<HTMLInputElement>(null)

  const [username, setUsername]   = useState("")
  const [password, setPassword]   = useState("")
  const [showPw, setShowPw]       = useState(false)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [shake, setShake]         = useState(false)
  const [networkError, setNetworkError] = useState(false)
  const [ssoEnabled, setSsoEnabled] = useState(false)
  const [webauthnEnabled, setWebauthnEnabled] = useState(false)
  const [passkeyLoading, setPasskeyLoading] = useState(false)

  // Password change modal state
  const [showChangePw, setShowChangePw]     = useState(false)
  const [newPw, setNewPw]                   = useState("")
  const [confirmPw, setConfirmPw]           = useState("")
  const [showNewPw, setShowNewPw]           = useState(false)
  const [changingPw, setChangingPw]         = useState(false)
  const [changeError, setChangeError]       = useState<string | null>(null)
  const [pendingToken, setPendingToken]     = useState<string | null>(null)

  useEffect(() => {
    // SSO return leg: /login?sso=1 arrives with the datapond_token cookie set by
    // the backend callback. Promote it into localStorage (saveAuth) and enter.
    const params = new URLSearchParams(window.location.search)
    if (params.get("sso") === "1") {
      const m = document.cookie.match(/(?:^|;\s*)datapond_token=([^;]+)/)
      const ssoToken = m?.[1]
      if (ssoToken) {
        fetch("/api/auth/me", { headers: { Authorization: `Bearer ${ssoToken}` } })
          .then(r => { if (!r.ok) throw new Error("sso session invalid"); return r.json() })
          .then(me => { saveAuth(ssoToken, me); window.location.replace("/dashboard") })
          .catch(() => { clearAuth(); setError("SSO sign-in failed. Please try again.") })
        return
      }
    }
    if (params.get("error") === "sso_failed") {
      const reason = params.get("reason") ?? "unknown"
      queueMicrotask(() => setError(`SSO sign-in failed (${reason}). Contact your administrator or sign in with a local account.`))
    }
    // Feature flag: show the SSO button only when the backend (enterprise image +
    // OIDC_ENABLED) reports it. Fail-quiet: button simply doesn't render.
    fetch("/api/capabilities").then(r => r.ok ? r.json() : null)
      .then(caps => {
        setSsoEnabled(Boolean(caps?.sso))
        setWebauthnEnabled(Boolean(caps?.webauthn))
      }).catch(() => {})

    // Auth state lives in BOTH localStorage (no expiry) and the cookie (24h,
    // checked by proxy.ts). If only the cookie has expired, blindly bouncing to
    // /dashboard loops forever: proxy → /login → here → /dashboard → proxy …
    // So validate the session server-side first; valid → repair the cookie and
    // go, invalid → clear the stale localStorage state and stay on login.
    if (isAuthenticated()) {
      const token = localStorage.getItem("datapond_token")
      fetch("/api/auth/me", { headers: token ? { Authorization: `Bearer ${token}` } : {} })
        .then(r => {
          if (!r.ok) throw new Error("session invalid")
          if (token) document.cookie = `datapond_token=${token}; path=/; max-age=${24 * 3600}; SameSite=Lax`
          window.location.replace("/dashboard")
        })
        .catch(() => {
          clearAuth()
          setError("Your session has expired. Please sign in again.")
        })
    }
    usernameRef.current?.focus()

    // Detect network status
    const handleOffline = () => setNetworkError(true)
    const handleOnline  = () => setNetworkError(false)
    window.addEventListener("offline", handleOffline)
    window.addEventListener("online",  handleOnline)
    if (!navigator.onLine) queueMicrotask(() => setNetworkError(true))
    return () => {
      window.removeEventListener("offline", handleOffline)
      window.removeEventListener("online",  handleOnline)
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) return
    setLoading(true)
    setError(null)
    try {
      const user = await login(username, password)
      if (user.require_password_change) {
        // Store token but require password change before entering app
        setPendingToken(localStorage.getItem("datapond_token"))
        setShowChangePw(true)
        setLoading(false)
        return
      }
      window.location.replace("/dashboard")
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Login failed"
      setError(msg)
      setShake(true)
      setTimeout(() => setShake(false), 500)
      setPassword("")
      setLoading(false)
    }
  }

  const passkeyLogin = async () => {
    setPasskeyLoading(true)
    setError(null)
    try {
      const beginResponse = await fetch("/api/auth/webauthn/authenticate/begin", { method: "POST" })
      if (!beginResponse.ok) {
        throw new Error(await responseErrorMessage(beginResponse, "Passkey sign-in failed"))
      }
      let begin: { options?: unknown; nonce?: unknown }
      try {
        begin = await beginResponse.json()
      } catch {
        throw new Error("Passkey sign-in could not start because the server returned an invalid response.")
      }
      const credential = await startAuthentication({ optionsJSON: begin.options as Parameters<typeof startAuthentication>[0]["optionsJSON"] })
      const res = await fetch("/api/auth/webauthn/authenticate/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nonce: begin.nonce, credential }),
      })
      if (!res.ok) {
        throw new Error(await responseErrorMessage(res, "Passkey sign-in failed"))
      }
      let data: { access_token?: unknown; user?: AuthUser }
      try {
        data = await res.json()
      } catch {
        throw new Error("Passkey sign-in succeeded, but the server returned an invalid response.")
      }
      if (typeof data.access_token !== "string" || !data.user) {
        throw new Error("Passkey sign-in succeeded, but the server returned an invalid response.")
      }
      // Same success path as password login: persist the token/user first...
      saveAuth(data.access_token, data.user)
      if (data.user?.require_password_change) {
        // ...but honor a pending forced password change exactly like the password
        // path does: gate on the modal instead of entering the app.
        setPendingToken(data.access_token)
        setShowChangePw(true)
        setPasskeyLoading(false)
        return
      }
      window.location.replace("/dashboard")
    } catch (err) {
      const msg = err instanceof TypeError
        ? "Unable to reach the passkey sign-in service. Check your connection and try again."
        : err instanceof Error
          ? err.message
          : "Passkey sign-in failed"
      setError(msg)
      setPasskeyLoading(false)
    }
  }

  const handleChangePassword = async () => {
    setChangeError(null)
    if (newPw.length < 6) { setChangeError("Password must be at least 6 characters"); return }
    if (newPw !== confirmPw) { setChangeError("Passwords do not match"); return }
    setChangingPw(true)
    try {
      const res = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${pendingToken}` },
        body: JSON.stringify({ new_password: newPw }),
      })
      if (!res.ok) {
        throw new Error(await responseErrorMessage(res, "Password change failed"))
      }
      setShowChangePw(false)
      window.location.replace("/dashboard")
    } catch (e) {
      setChangeError(e instanceof TypeError
        ? "Unable to reach the password service. Check your connection and try again."
        : e instanceof Error
          ? e.message
          : "Password change failed. Please try again.")
    } finally {
      setChangingPw(false)
    }
  }

  return (
    <>
    {/* Network error banner */}
    {networkError && (
      <div role="alert" aria-live="assertive" className="fixed top-0 left-0 right-0 z-50 flex items-center justify-center gap-2 bg-destructive px-4 py-2 text-sm text-white">
        <WifiOff className="h-4 w-4 shrink-0" />
        <span>Cannot connect to server. Please check your network connection.</span>
        <button
          onClick={() => fetch("/api/health").then(() => setNetworkError(false)).catch(() => {})}
          className="ml-3 underline underline-offset-2 hover:no-underline font-medium"
        >
          Retry
        </button>
      </div>
    )}

    <div className={`min-h-screen flex ${networkError ? "pt-10" : ""}`}>

      {/* ── Left panel — deep-pond signature (dp-gradient: cyan→blue→indigo) ── */}
      <div className="hidden lg:flex lg:w-[52%] relative flex-col justify-between overflow-hidden"
        style={{ background: "linear-gradient(140deg, #04171c 0%, #071d2e 55%, #0a1430 100%)" }}>

        {/* Grid pattern */}
        <div className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: `linear-gradient(rgba(34,211,238,0.8) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(34,211,238,0.8) 1px, transparent 1px)`,
            backgroundSize: "40px 40px",
          }} />
        <div className="absolute top-1/4 left-1/3 w-96 h-96 rounded-full opacity-10 blur-3xl"
          style={{ background: "radial-gradient(circle, #22d3ee 0%, transparent 70%)" }} />
        <div className="absolute bottom-1/3 right-1/4 w-64 h-64 rounded-full opacity-10 blur-3xl"
          style={{ background: "radial-gradient(circle, #818cf8 0%, transparent 70%)" }} />

        <div className="relative z-10 flex flex-col justify-between h-full px-12 py-10">
          {/* Logo */}
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

          {/* Hero */}
          <div className="space-y-6">
            <div>
              <h2 className="text-4xl font-bold text-white leading-tight mb-3">
                Governed AI.<br />
                <span style={{ background: "linear-gradient(90deg, #22d3ee, #818cf8)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                  Without the lock-in.
                </span>
              </h2>
              <p style={{ color: "#9fb3bf" }} className="text-base leading-relaxed max-w-sm">
                Build production-oriented RAG and agent data flows on infrastructure you control — with portable storage, vector, and model contracts.
              </p>
            </div>
            <div className="space-y-4">
              {FEATURES.map(({ icon: Icon, title, desc }) => (
                <div key={title} className="flex items-start gap-3">
                  <div className="h-8 w-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                    style={{ background: "rgba(34,211,238,0.14)", border: "1px solid rgba(34,211,238,0.22)" }}>
                    <Icon className="h-4 w-4" style={{ color: "#22d3ee" }} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white">{title}</p>
                    <p className="text-xs leading-relaxed mt-0.5" style={{ color: "#7c93a3" }}>{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <p className="text-xs" style={{ color: "#3f5561" }}>
            © 2026 DataPond · Portable AI Data Foundation
          </p>
        </div>
      </div>

      {/* ── Right panel: login form ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-background">
        <div className="w-full max-w-sm space-y-8">

          {/* Mobile logo */}
          <div className="lg:hidden text-center space-y-1">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-2xl mx-auto mb-2"
              style={{ background: "linear-gradient(120deg, #22d3ee 0%, #60a5fa 55%, #818cf8 100%)" }}>
              <Layers className="h-6 w-6 text-white" />
            </div>
            <h1 className="text-2xl font-bold">DataPond</h1>
            <p className="text-sm text-muted-foreground">Portable AI Data Foundation</p>
          </div>

          <div className="space-y-1">
            <h2 className="text-2xl font-bold tracking-tight">Sign in</h2>
            <p className="text-sm text-muted-foreground">Enter your credentials to access the platform</p>
          </div>

          <form onSubmit={handleSubmit}
            className={`space-y-5 ${shake ? "[animation:shake_0.5s_ease-in-out]" : ""}`}>
            <div className="space-y-2">
              <Label htmlFor="username" className="text-sm font-medium">Username</Label>
              <Input
                ref={usernameRef}
                id="username"
                value={username}
                onChange={e => { setUsername(e.target.value); setError(null) }}
                placeholder="Enter your username"
                autoComplete="username"
                disabled={loading}
                className={`h-10 ${error ? "border-destructive" : ""}`}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password" className="text-sm font-medium">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPw ? "text" : "password"}
                  value={password}
                  onChange={e => { setPassword(e.target.value); setError(null) }}
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  disabled={loading}
                  className={`h-10 pr-10 ${error ? "border-destructive" : ""}`}
                />
                <button
                  type="button"
                  onClick={() => setShowPw(v => !v)}
                  aria-label={showPw ? "Hide password" : "Show password"}
                  title={showPw ? "Hide password" : "Show password"}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div role="alert" aria-live="assertive" className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5">
                <Lock className="h-4 w-4 text-destructive shrink-0" />
                <p className="text-sm text-destructive">{error}</p>
              </div>
            )}

            <Button type="submit" className="w-full h-10 font-medium"
              disabled={loading || !username || !password}>
              {loading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Signing in…</> : "Sign in"}
            </Button>

            {webauthnEnabled && (
              <Button type="button" variant="outline" className="w-full h-10 font-medium mt-2"
                      disabled={passkeyLoading} onClick={passkeyLogin}>
                {passkeyLoading
                  ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Waiting for passkey…</>
                  : <><Fingerprint className="h-4 w-4 mr-2" />Sign in with a passkey</>}
              </Button>
            )}

            {ssoEnabled && (
              <Button type="button" variant="outline" className="w-full h-10 font-medium mt-2"
                      onClick={() => { window.location.href = "/api/auth/oidc/login" }}>
                Sign in with SSO
              </Button>
            )}
          </form>
        </div>
      </div>
    </div>

    {/* ── First-login: Force password change modal ── */}
    {showChangePw && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="bg-background rounded-2xl border shadow-2xl w-full max-w-md mx-4 overflow-hidden">
          {/* Header */}
          <div className="px-6 py-5 border-b bg-amber-50/50 dark:bg-amber-950/20">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-amber-100 flex items-center justify-center">
                <AlertTriangle className="h-5 w-5 text-amber-600" />
              </div>
              <div>
                <h3 className="text-base font-semibold">Password Change Required</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Set a new password to continue</p>
              </div>
            </div>
          </div>

          {/* Body */}
          <div className="px-6 py-5 space-y-4">
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-3 text-sm text-amber-700">
              This is your first login or you are using a temporary password. Please set a new password to continue accessing the platform.
            </div>

            <div className="space-y-2">
              <Label htmlFor="new-password" className="text-sm font-medium">New Password</Label>
              <div className="relative">
                <Input
                  id="new-password"
                  type={showNewPw ? "text" : "password"}
                  value={newPw}
                  onChange={e => { setNewPw(e.target.value); setChangeError(null) }}
                  placeholder="Minimum 6 characters"
                  className="pr-10"
                  autoComplete="new-password"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setShowNewPw(v => !v)}
                  aria-label={showNewPw ? "Hide new password" : "Show new password"}
                  title={showNewPw ? "Hide new password" : "Show new password"}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {showNewPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="confirm-new-password" className="text-sm font-medium">Confirm New Password</Label>
              <Input
                id="confirm-new-password"
                type="password"
                value={confirmPw}
                onChange={e => { setConfirmPw(e.target.value); setChangeError(null) }}
                placeholder="Repeat new password"
                autoComplete="new-password"
                onKeyDown={e => e.key === "Enter" && handleChangePassword()}
              />
            </div>

            {changeError && (
              <div role="alert" aria-live="assertive" className="flex items-center gap-2 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
                <Lock className="h-4 w-4 shrink-0" />
                {changeError}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t bg-muted/30 flex justify-end">
            <Button onClick={handleChangePassword} disabled={changingPw || !newPw || !confirmPw}>
              {changingPw ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Changing…</> : "Change Password"}
            </Button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}
