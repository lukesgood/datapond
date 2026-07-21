"use client"

import { useState } from "react"
import { X, HelpCircle, Search, ExternalLink } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import Link from "next/link"

interface HelpSection {
  title: string
  content: string
}

interface HelpPanelProps {
  isOpen: boolean
  onClose: () => void
  title: string
  sections: HelpSection[]
  quickLinks?: Array<{ label: string; href: string }>
}

export function HelpPanel({ isOpen, onClose, title, sections, quickLinks = [] }: HelpPanelProps) {
  const [searchQuery, setSearchQuery] = useState("")
  const [openSections, setOpenSections] = useState<string[]>([sections[0]?.title])

  const filteredSections = sections.filter(
    section =>
      section.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      section.content.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const toggleSection = (sectionTitle: string) => {
    setOpenSections(prev =>
      prev.includes(sectionTitle)
        ? prev.filter(t => t !== sectionTitle)
        : [...prev, sectionTitle]
    )
  }

  if (!isOpen) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-background/80 backdrop-blur-sm z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-full sm:w-[480px] bg-background border-l shadow-lg z-50 overflow-hidden flex flex-col animate-in slide-in-from-right">
        {/* Header */}
        <div className="border-b p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <HelpCircle className="h-5 w-5 text-primary" />
              <h2 className="text-lg font-semibold">{title}</h2>
            </div>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search help..."
              className="pl-9"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Quick Links */}
          {quickLinks.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-muted-foreground">Quick Links</h3>
              <div className="space-y-1">
                {quickLinks.map((link, idx) => (
                  <Link
                    key={idx}
                    href={link.href}
                    className="flex items-center gap-2 text-sm text-primary hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" />
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Sections */}
          <div className="space-y-2">
            {filteredSections.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No results found for &quot;{searchQuery}&quot;
              </div>
            ) : (
              filteredSections.map((section, idx) => (
                <Collapsible
                  key={idx}
                  open={openSections.includes(section.title)}
                  onOpenChange={() => toggleSection(section.title)}
                >
                  <CollapsibleTrigger className="flex items-center justify-between w-full p-3 text-left hover:bg-muted rounded-lg transition-colors">
                    <span className="font-medium">{section.title}</span>
                    <Badge variant="outline" className="ml-2">
                      {openSections.includes(section.title) ? "−" : "+"}
                    </Badge>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="px-3 pt-2 pb-3">
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <p className="text-sm text-muted-foreground whitespace-pre-line">
                        {section.content}
                      </p>
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              ))
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="border-t p-4 bg-muted/30">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Need more help?</span>
            <Link href="/help" className="text-primary hover:underline">
              View all guides
            </Link>
          </div>
        </div>
      </div>
    </>
  )
}

export function HelpButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onClick}>
      <HelpCircle className="h-4 w-4 mr-2" />
      Help
    </Button>
  )
}
