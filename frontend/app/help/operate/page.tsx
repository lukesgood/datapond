"use client"

import Link from "next/link"
import { Settings2 } from "lucide-react"
import { GuideHeader } from "@/components/help/ai-ops-guide"
import { useHelpLocale } from "@/components/help/locale"
import { DeploymentConfig } from "@/components/help/deployment-config"
import { OPERATE_PAGE } from "@/lib/help-ai-ops"

/** How an operator changes this deployment's configuration. Live specs and usage are
 *  in Infrastructure. */
export default function OperateHelpPage() {
  const { t } = useHelpLocale()
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <GuideHeader crumb={OPERATE_PAGE.crumb} title={OPERATE_PAGE.title}
        subtitle={<>{t(OPERATE_PAGE.subtitle)}{" "}
          <Link href="/services?tab=system" className="text-primary hover:underline">Infrastructure → System</Link>.</>}
        Icon={Settings2} iconBox="bg-muted" iconColor="text-muted-foreground" />
      <DeploymentConfig />
    </div>
  )
}
