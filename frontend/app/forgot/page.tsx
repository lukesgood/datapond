"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Loader2, Layers, MailCheck, ArrowLeft } from "lucide-react"

export default function ForgotPasswordPage() {
  const [email, setEmail]     = useState("")
  const [loading, setLoading] = useState(false)
  const [sent, setSent]       = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email) return
    setLoading(true)
    try {
      // Fire-and-forget: the backend always returns a generic 200 (no user
      // enumeration), so we show the same confirmation regardless of the result.
      await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      })
    } catch {
      // Never reveal delivery/lookup state — always land on the neutral confirmation.
    }
    setSent(true)
    setLoading(false)
  }

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
              Trouble signing in?
            </h2>
            <p style={{ color: "#9fb3bf" }} className="text-base leading-relaxed max-w-sm">
              Enter your email and we&apos;ll send a secure link to reset your password. The link expires in 30 minutes.
            </p>
          </div>
          <p className="text-xs" style={{ color: "#3f5561" }}>
            © 2026 DataPond · Portable AI Data Foundation
          </p>
        </div>
      </div>

      {/* ── Right panel: forgot form ── */}
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

          {sent ? (
            <div className="space-y-6">
              <div className="flex flex-col items-center text-center space-y-3">
                <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center">
                  <MailCheck className="h-6 w-6 text-primary" />
                </div>
                <div className="space-y-1">
                  <h2 className="text-2xl font-bold tracking-tight">Check your email</h2>
                  <p className="text-sm text-muted-foreground">
                    If that email exists, we&apos;ve sent a reset link. It expires in 30 minutes.
                  </p>
                </div>
              </div>
              <a href="/login"
                className="flex items-center justify-center gap-2 text-sm font-medium text-primary hover:underline underline-offset-2">
                <ArrowLeft className="h-4 w-4" />
                Back to sign in
              </a>
            </div>
          ) : (
            <>
              <div className="space-y-1">
                <h2 className="text-2xl font-bold tracking-tight">Forgot password</h2>
                <p className="text-sm text-muted-foreground">
                  Enter the email associated with your account and we&apos;ll send a reset link.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="email" className="text-sm font-medium">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                    autoFocus
                    disabled={loading}
                    className="h-10"
                  />
                </div>

                <Button type="submit" className="w-full h-10 font-medium" disabled={loading || !email}>
                  {loading ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Sending…</> : "Send reset link"}
                </Button>

                <a href="/login"
                  className="flex items-center justify-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground">
                  <ArrowLeft className="h-4 w-4" />
                  Back to sign in
                </a>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
