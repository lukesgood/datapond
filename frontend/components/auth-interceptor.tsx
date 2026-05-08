"use client"

import { useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import { installAuthInterceptor, clearAuth } from "@/lib/auth"
import { Lock, WifiOff } from "lucide-react"
import { Button } from "@/components/ui/button"

export function AuthInterceptor() {
  const router = useRouter()
  const pathname = usePathname()
  const [sessionExpired, setSessionExpired] = useState(false)
  const [networkError, setNetworkError] = useState(false)

  useEffect(() => {
    installAuthInterceptor()

    // Listen for network status
    const onOffline = () => setNetworkError(true)
    const onOnline  = () => setNetworkError(false)
    window.addEventListener("offline", onOffline)
    window.addEventListener("online",  onOnline)

    // Listen for session expiry event from auth interceptor
    const onExpired = () => {
      if (!pathname.startsWith("/login")) setSessionExpired(true)
    }
    window.addEventListener("datapond:session-expired", onExpired)

    return () => {
      window.removeEventListener("offline", onOffline)
      window.removeEventListener("online",  onOnline)
      window.removeEventListener("datapond:session-expired", onExpired)
    }
  }, [pathname])

  const handleRelogin = () => {
    clearAuth()
    setSessionExpired(false)
    router.push("/login")
  }

  const handleRetry = async () => {
    try {
      await fetch("/api/health")
      setNetworkError(false)
    } catch {}
  }

  return (
    <>
      {/* Network error banner */}
      {networkError && !pathname.startsWith("/login") && (
        <div className="fixed top-0 left-0 right-0 z-[100] flex items-center justify-center gap-2 bg-destructive px-4 py-2 text-sm text-white">
          <WifiOff className="h-4 w-4 shrink-0" />
          <span>Cannot connect to server. Please check your network.</span>
          <button onClick={handleRetry}
            className="ml-3 underline underline-offset-2 hover:no-underline font-medium">
            Retry
          </button>
        </div>
      )}

      {/* Session expired overlay */}
      {sessionExpired && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="bg-background rounded-2xl border shadow-2xl w-full max-w-sm mx-4 overflow-hidden">
            <div className="px-6 py-6 text-center space-y-4">
              <div className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-muted mx-auto">
                <Lock className="h-7 w-7 text-muted-foreground" />
              </div>
              <div>
                <h3 className="text-lg font-semibold">Session Expired</h3>
                <p className="text-sm text-muted-foreground mt-1">
                  Your session has expired. Please sign in again to continue.
                </p>
              </div>
            </div>
            <div className="px-6 pb-6">
              <Button className="w-full" onClick={handleRelogin}>
                Sign in again
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
