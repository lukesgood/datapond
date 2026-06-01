"use client"

import { useState, useEffect } from "react"
import { X, ExternalLink, Maximize2, Minimize2 } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { serviceUrls } from "@/lib/urls"

interface JupyterEmbedProps {
  notebook: {
    name: string
    path: string
  } | null
  open: boolean
  onClose: () => void
}

export function JupyterEmbed({ notebook, open, onClose }: JupyterEmbedProps) {
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [iframeError, setIframeError] = useState(false)

  useEffect(() => {
    setIframeError(false)
  }, [notebook])

  if (!notebook) return null

  const jupyterUrl = `${serviceUrls.jupyter()}/lab/tree${notebook.path}?token=jupyter`

  const openInNewTab = () => {
    window.open(jupyterUrl, "_blank")
  }

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen)
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent
        className={`${
          isFullscreen
            ? "max-w-[100vw] max-h-[100vh] w-screen h-screen"
            : "max-w-[90vw] max-h-[90vh]"
        } p-0`}
        showCloseButton={false}
      >
        <DialogHeader className="p-4 pb-3 border-b bg-muted/50">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-base">{notebook.name}</DialogTitle>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={toggleFullscreen}
                title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
              >
                {isFullscreen ? (
                  <Minimize2 className="h-4 w-4" />
                ) : (
                  <Maximize2 className="h-4 w-4" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={openInNewTab}
                title="Open in new tab"
              >
                <ExternalLink className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onClose}
                title="Close"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </DialogHeader>

        <div className="relative flex-1 overflow-hidden">
          {iframeError ? (
            <div className="p-4">
              <Alert variant="destructive">
                <AlertDescription>
                  Failed to load JupyterLab. The notebook may not exist or JupyterLab may be unavailable.
                  <div className="mt-2">
                    <Button variant="outline" size="sm" onClick={openInNewTab}>
                      <ExternalLink className="mr-2 h-4 w-4" />
                      Try opening in new tab
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            </div>
          ) : (
            <iframe
              src={jupyterUrl}
              className={`w-full border-0 ${
                isFullscreen ? "h-[calc(100vh-60px)]" : "h-[calc(90vh-60px)]"
              }`}
              sandbox="allow-same-origin allow-scripts allow-forms allow-downloads"
              onError={() => setIframeError(true)}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
