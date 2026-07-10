"use client"

import { useState, useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { login, isAuthenticated, clearAuth, saveAuth } from "@/lib/auth"
import { Loader2, Eye, EyeOff, ShieldCheck, Layers, Zap, Lock, AlertTriangle, WifiOff, Fingerprint } from "lucide-react"
import { startAuthentication } from "@simplewebauthn/browser"

const FEATURES = [
  {
    icon: ShieldCheck,
    title: "Sovereign Infrastructure",
    desc: "Run a full-featured lakehouse inside your network — air-gapped, on-prem, or private cloud.",
  },
  {
    icon: Layers,
    title: "Iceberg Lakehouse",
    desc: "ACID transactions, schema evolution, and time-travel queries on your own storage.",
  },
  {
    icon: Zap,
    title: "Real-time + Batch",
    desc: "RisingWave streaming SQL and Airflow batch pipelines — unified in one platform.",
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
  const [pendingUserId, setPendingUserId]   = useState<string | null>(null)
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
          .catch(() => { clearAuth(); setError("SSO 로그인에 실패했습니다. 다시 시도해 주세요.") })
        return
      }
    }
    if (params.get("error") === "sso_failed") {
      const reason = params.get("reason") ?? "unknown"
      setError(`SSO 로그인 실패 (${reason}). 관리자에게 문의하거나 로컬 계정으로 로그인하세요.`)
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
          setError("세션이 만료되었습니다. 다시 로그인해 주세요.")
        })
    }
    usernameRef.current?.focus()

    // Detect network status
    const handleOffline = () => setNetworkError(true)
    const handleOnline  = () => setNetworkError(false)
    window.addEventListener("offline", handleOffline)
    window.addEventListener("online",  handleOnline)
    if (!navigator.onLine) setNetworkError(true)
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
        setPendingUserId(user.id)
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
      const begin = await fetch("/api/auth/webauthn/authenticate/begin", { method: "POST" })
        .then(r => { if (!r.ok) throw new Error("Passkey sign-in is unavailable"); return r.json() })
      const credential = await startAuthentication({ optionsJSON: begin.options })
      const res = await fetch("/api/auth/webauthn/authenticate/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nonce: begin.nonce, credential }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => null)
        throw new Error(d?.detail ?? "Passkey sign-in failed")
      }
      const data = await res.json()
      // Same success path as password login: persist the token/user + navigate.
      saveAuth(data.access_token, data.user)
      window.location.replace("/dashboard")
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Passkey sign-in failed"
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
        const d = await res.json()
        throw new Error(d.detail ?? "Failed to change password")
      }
      setShowChangePw(false)
      window.location.replace("/dashboard")
    } catch (e) {
      setChangeError(e instanceof Error ? e.message : "Failed")
    } finally {
      setChangingPw(false)
    }
  }

  return (
    <>
    {/* Network error banner */}
    {networkError && (
      <div className="fixed top-0 left-0 right-0 z-50 flex items-center justify-center gap-2 bg-destructive px-4 py-2 text-sm text-white">
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

      {/* ── Left panel ── */}
      <div className="hidden lg:flex lg:w-[52%] relative flex-col justify-between overflow-hidden"
        style={{ background: "linear-gradient(135deg, #0a0f1e 0%, #0d1f3c 50%, #0a1628 100%)" }}>

        {/* Grid pattern */}
        <div className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: `linear-gradient(rgba(99,179,237,0.8) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(99,179,237,0.8) 1px, transparent 1px)`,
            backgroundSize: "40px 40px",
          }} />
        <div className="absolute top-1/4 left-1/3 w-96 h-96 rounded-full opacity-10 blur-3xl"
          style={{ background: "radial-gradient(circle, #3b82f6 0%, transparent 70%)" }} />
        <div className="absolute bottom-1/3 right-1/4 w-64 h-64 rounded-full opacity-10 blur-3xl"
          style={{ background: "radial-gradient(circle, #6366f1 0%, transparent 70%)" }} />

        <div className="relative z-10 flex flex-col justify-between h-full px-12 py-10">
          {/* Logo */}
          <div>
            <div className="flex items-center gap-3 mb-1">
              <div className="h-9 w-9 rounded-xl flex items-center justify-center"
                style={{ background: "linear-gradient(135deg, #3b82f6, #6366f1)" }}>
                <Layers className="h-5 w-5 text-white" />
              </div>
              <span className="text-2xl font-bold tracking-tight text-white">DataPond</span>
            </div>
            <p className="text-sm ml-12" style={{ color: "#64748b" }}>AI-Native Lakehouse Platform</p>
          </div>

          {/* Hero */}
          <div className="space-y-6">
            <div>
              <h2 className="text-4xl font-bold text-white leading-tight mb-3">
                Your Data.<br />
                <span style={{ background: "linear-gradient(90deg, #60a5fa, #a78bfa)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                  Your Infrastructure.
                </span>
              </h2>
              <p style={{ color: "#94a3b8" }} className="text-base leading-relaxed max-w-sm">
                Full-stack AI lakehouse built for regulated, air-gapped, and sovereign infrastructure — deployed entirely within your environment.
              </p>
            </div>
            <div className="space-y-4">
              {FEATURES.map(({ icon: Icon, title, desc }) => (
                <div key={title} className="flex items-start gap-3">
                  <div className="h-8 w-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                    style={{ background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.25)" }}>
                    <Icon className="h-4 w-4" style={{ color: "#60a5fa" }} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white">{title}</p>
                    <p className="text-xs leading-relaxed mt-0.5" style={{ color: "#64748b" }}>{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <p className="text-xs" style={{ color: "#334155" }}>
            © 2026 DataPond · AI-Native Lakehouse for Sovereign Infrastructure
          </p>
        </div>
      </div>

      {/* ── Right panel: login form ── */}
      <div className="flex-1 flex items-center justify-center px-6 py-12 bg-background">
        <div className="w-full max-w-sm space-y-8">

          {/* Mobile logo */}
          <div className="lg:hidden text-center space-y-1">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-2xl mx-auto mb-2"
              style={{ background: "linear-gradient(135deg, #3b82f6, #6366f1)" }}>
              <Layers className="h-6 w-6 text-white" />
            </div>
            <h1 className="text-2xl font-bold">DataPond</h1>
            <p className="text-sm text-muted-foreground">AI-Native Lakehouse</p>
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
                <button type="button" onClick={() => setShowPw(v => !v)} tabIndex={-1}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors">
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5">
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

          <div className="rounded-lg border bg-muted/40 px-4 py-3 space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Default credentials</p>
            <div className="flex items-center gap-4 text-xs">
              <span>Username: <code className="font-mono bg-muted px-1 py-0.5 rounded">admin</code></span>
              <span>Password: <code className="font-mono bg-muted px-1 py-0.5 rounded">datapond123</code></span>
            </div>
          </div>
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
              <Label className="text-sm font-medium">New Password</Label>
              <div className="relative">
                <Input
                  type={showNewPw ? "text" : "password"}
                  value={newPw}
                  onChange={e => { setNewPw(e.target.value); setChangeError(null) }}
                  placeholder="Minimum 6 characters"
                  className="pr-10"
                  autoFocus
                />
                <button type="button" onClick={() => setShowNewPw(v => !v)} tabIndex={-1}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showNewPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium">Confirm New Password</Label>
              <Input
                type="password"
                value={confirmPw}
                onChange={e => { setConfirmPw(e.target.value); setChangeError(null) }}
                placeholder="Repeat new password"
                onKeyDown={e => e.key === "Enter" && handleChangePassword()}
              />
            </div>

            {changeError && (
              <div className="flex items-center gap-2 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
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
