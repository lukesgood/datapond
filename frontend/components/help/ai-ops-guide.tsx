"use client"

import type { ComponentType, ReactNode } from "react"
import Link from "next/link"
import { Info } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { HelpLocaleToggle, useHelpLocale } from "@/components/help/locale"
import type { Guide, Section } from "@/lib/help-ai-ops"

/** `code` and **bold** spans inside a translated string. */
export function Rich({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("`") && p.endsWith("`") && p.length > 2)
          return <code key={i} className="rounded bg-muted px-1 font-mono text-xs text-foreground">{p.slice(1, -1)}</code>
        if (p.startsWith("**") && p.endsWith("**") && p.length > 4)
          return <span key={i} className="font-medium text-foreground">{p.slice(2, -2)}</span>
        return <span key={i}>{p}</span>
      })}
    </>
  )
}

export function SectionCard({ s, children }: { s: Section; children?: ReactNode }) {
  const { t } = useHelpLocale()
  return (
    <Card>
      <CardHeader><CardTitle>{t(s.title)}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {s.paras?.map((p, i) => (
          <p key={i} className="text-sm text-muted-foreground"><Rich text={t(p)} /></p>
        ))}
        {s.bullets && (
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground marker:text-primary/60">
            {s.bullets.map((b, i) => <li key={i}><Rich text={t(b)} /></li>)}
          </ul>
        )}
        {s.code && <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs"><code>{s.code}</code></pre>}
        {children}
        {s.links && (
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {s.links.map((k) => (
              <Link key={k.href + k.label.en} href={k.href} className="text-primary hover:underline">{t(k.label)}</Link>
            ))}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function GuideHeader({ crumb, title, subtitle, Icon, iconBox, iconColor }: {
  crumb: Guide["crumb"]; title: Guide["title"]; subtitle: ReactNode
  Icon: ComponentType<{ className?: string }>; iconBox: string; iconColor: string
}) {
  const { t } = useHelpLocale()
  return (
    <>
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbLink href="/help">Guides</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>{t(crumb)}</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="flex items-start gap-4">
        <div className={`inline-flex rounded-lg p-3 ${iconBox}`}><Icon className={`h-8 w-8 ${iconColor}`} /></div>
        <div className="flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
            <HelpLocaleToggle />
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">{t(title)}</h1>
          <p className="mt-2 text-muted-foreground">{subtitle}</p>
        </div>
      </div>
    </>
  )
}

/** A whole guide from its content: header, optional note, section cards, limits. */
export function AiOpsGuide({ guide, Icon, iconBox, iconColor }: {
  guide: Guide; Icon: ComponentType<{ className?: string }>; iconBox: string; iconColor: string
}) {
  const { t } = useHelpLocale()
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <GuideHeader crumb={guide.crumb} title={guide.title} subtitle={t(guide.subtitle)} Icon={Icon} iconBox={iconBox} iconColor={iconColor} />
      {guide.alert && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertTitle>{t(guide.alert.title)}</AlertTitle>
          <AlertDescription>{t(guide.alert.body)}</AlertDescription>
        </Alert>
      )}
      {guide.sections.map((s) => <SectionCard key={s.title.en} s={s} />)}
      {guide.limits && (
        <Card>
          <CardHeader><CardTitle>{t(guide.limits.title)}</CardTitle></CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground marker:text-primary/60">
              {guide.limits.items.map((it) => <li key={it.en}><Rich text={t(it)} /></li>)}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
