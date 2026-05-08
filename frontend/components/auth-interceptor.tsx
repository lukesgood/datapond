"use client"
import { useEffect } from "react"
import { installAuthInterceptor } from "@/lib/auth"

export function AuthInterceptor() {
  useEffect(() => { installAuthInterceptor() }, [])
  return null
}
