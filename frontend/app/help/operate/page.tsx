"use client"

import Link from "next/link"
import { Settings2 } from "lucide-react"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { DeploymentConfig } from "@/components/help/deployment-config"

/** How an operator changes this deployment's configuration. Was the Settings → System
 *  tab: instructions, not settings. Live specs and usage are in Infrastructure. */
export default function OperateHelpPage() {
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbLink href="/help">Guides</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>Change the configuration</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-muted">
          <Settings2 className="h-8 w-8 text-muted-foreground" />
        </div>
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Change this deployment&apos;s configuration</h1>
          <p className="mt-2 text-muted-foreground">
            Configuration is the Helm values of the profile this deployment runs; the commands
            below are filled in for it. Live specs and resource usage are in{" "}
            <Link href="/services?tab=system" className="text-primary hover:underline">Infrastructure → System</Link>.
          </p>
        </div>
      </div>

      <DeploymentConfig />
    </div>
  )
}
