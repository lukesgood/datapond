import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ToastProvider } from "@/lib/toast"
import { ConfirmProvider } from "@/lib/confirm"
import { AuthInterceptor } from "@/components/auth-interceptor"
import { ConditionalLayout } from "@/components/conditional-layout"

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" })

export const metadata: Metadata = {
  title: "DataPond - AI-Native Lakehouse Platform",
  description: "Enterprise data platform for sovereign infrastructure",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex font-sans">
        <ToastProvider>
          <ConfirmProvider>
            <AuthInterceptor />
            <TooltipProvider>
              <ConditionalLayout>
                {children}
              </ConditionalLayout>
            </TooltipProvider>
          </ConfirmProvider>
        </ToastProvider>
      </body>
    </html>
  )
}
