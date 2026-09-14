import type { Metadata } from "next"
import { Geist_Mono, Inter } from "next/font/google"
import "./globals.css"
import { TooltipProvider } from "@/components/ui/tooltip"
import { PermissionProvider } from "@/lib/permissions"
import { ToastProvider } from "@/lib/toast"
import { ConfirmProvider } from "@/lib/confirm"
import { AuthInterceptor } from "@/components/auth-interceptor"
import { ConditionalLayout } from "@/components/conditional-layout"

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" })
// globals.css maps font-mono to --font-geist-mono. Without this font nothing defined
// that variable, so every code sample and key fell back to Inter.
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" })

export const metadata: Metadata = {
  title: "DataPond — Governed data tool server",
  description: "Cited RAG and governed SQL as tools for AI agents and apps, governed at the data layer: access, masking, audit, and per-caller spend.",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex font-sans">
        <ToastProvider>
          <ConfirmProvider>
            <AuthInterceptor />
            <TooltipProvider>
              <PermissionProvider>
                <ConditionalLayout>
                  {children}
                </ConditionalLayout>
              </PermissionProvider>
            </TooltipProvider>
          </ConfirmProvider>
        </ToastProvider>
      </body>
    </html>
  )
}
