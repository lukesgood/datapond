"use client"

import { useState } from "react"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { ConnectorField } from "@/lib/connectors"
import { Loader2, CheckCircle2, XCircle, Eye, EyeOff, ShieldCheck } from "lucide-react"

type ConnectionValue = string | number | boolean | null | undefined

function toInputValue(value: ConnectionValue): string | number {
  return typeof value === "string" || typeof value === "number" ? value : ""
}

function toChecked(value: ConnectionValue): boolean {
  return typeof value === "boolean" ? value : false
}

function toSelectValue(value: ConnectionValue): string | undefined {
  return typeof value === "string" ? value : undefined
}

interface ConnectionFormProps {
  fields: ConnectorField[]
  values: Record<string, ConnectionValue>
  onChange: (name: string, value: ConnectionValue) => void
  onTest?: () => Promise<void>
  testStatus?: "idle" | "testing" | "success" | "error"
  testMessage?: string
}

export function ConnectionForm({
  fields,
  values,
  onChange,
  onTest,
  testStatus = "idle",
  testMessage
}: ConnectionFormProps) {
  // Per-field secret reveal state (a form can carry more than one password field).
  const [revealed, setRevealed] = useState<Record<string, boolean>>({})

  const isEmpty = (field: ConnectorField) => {
    const value = values[field.name]
    if (typeof value === "boolean" || typeof value === "number") return false
    return !(typeof value === "string" && value.trim() !== "")
  }
  // Every required field must be filled before the connection can be tested.
  const missing = fields.filter((field) => field.required && isEmpty(field))
  const canTest = missing.length === 0
  const hasSecret = fields.some((field) => field.type === "password")

  return (
    <div className="space-y-6">
      {/* Two-column grid: half-width fields (host+port, username+password) pair on
          one row; everything else spans the full width. Stacks on narrow widths. */}
      <div className="grid grid-cols-2 gap-4">
        {fields.map((field) => {
          const reveal = revealed[field.name]
          return (
          <div key={field.name} className={`space-y-2 ${field.half ? "col-span-2 sm:col-span-1" : "col-span-2"}`}>
            <Label htmlFor={field.name}>
              {field.label}
              {field.required && <span className="text-destructive ml-1">*</span>}
            </Label>

            {field.type === "textarea" ? (
              <Textarea
                id={field.name}
                placeholder={field.placeholder}
                value={toInputValue(values[field.name] || "")}
                onChange={(e) => onChange(field.name, e.target.value)}
                required={field.required}
                className="font-mono text-sm min-h-[180px]"
              />
            ) : field.type === "password" ? (
              <div className="relative">
                <Input
                  id={field.name}
                  type={reveal ? "text" : "password"}
                  placeholder={field.placeholder}
                  value={toInputValue(values[field.name] || "")}
                  onChange={(e) => onChange(field.name, e.target.value)}
                  required={field.required}
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setRevealed((r) => ({ ...r, [field.name]: !r[field.name] }))}
                  aria-label={reveal ? `Hide ${field.label}` : `Show ${field.label}`}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:text-foreground"
                >
                  {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            ) : field.type === "text" ? (
              <Input
                id={field.name}
                type="text"
                placeholder={field.placeholder}
                value={toInputValue(values[field.name] || "")}
                onChange={(e) => onChange(field.name, e.target.value)}
                required={field.required}
              />
            ) : field.type === "number" ? (
              <Input
                id={field.name}
                type="number"
                placeholder={field.placeholder}
                value={toInputValue(values[field.name] || field.default || "")}
                onChange={(e) => {
                  const v = parseInt(e.target.value)
                  onChange(field.name, isNaN(v) ? (field.default ?? "") : v)
                }}
                required={field.required}
              />
            ) : field.type === "boolean" ? (
              <div className="flex items-center space-x-2">
                <Switch
                  id={field.name}
                  checked={toChecked(values[field.name] || field.default || false)}
                  onCheckedChange={(checked) => onChange(field.name, checked)}
                />
                <Label htmlFor={field.name} className="cursor-pointer">
                  {field.help || "Enable"}
                </Label>
              </div>
            ) : field.type === "select" ? (
              <Select
                value={toSelectValue(values[field.name] || field.default)}
                onValueChange={(value) => onChange(field.name, value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder={`Select ${field.label}`} />
                </SelectTrigger>
                <SelectContent>
                  {field.options?.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}

            {field.help && field.type !== "boolean" && (
              <p className="text-xs text-muted-foreground">{field.help}</p>
            )}
          </div>
          )
        })}
      </div>

      {/* Credential handling reassurance — only when the form actually collects a secret. */}
      {hasSecret && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-[var(--dp-good)]" />
          Credentials are encrypted at rest by the platform credential vault.
        </p>
      )}

      {/* Test Connection */}
      {onTest && (
        <div className="space-y-2">
          <Button
            type="button"
            variant="outline"
            onClick={onTest}
            disabled={testStatus === "testing" || !canTest}
            className="w-full"
          >
            {testStatus === "testing" && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            {testStatus === "success" && (
              <CheckCircle2 className="mr-2 h-4 w-4 text-green-500" />
            )}
            {testStatus === "error" && (
              <XCircle className="mr-2 h-4 w-4 text-destructive" />
            )}
            Test Connection
          </Button>

          {/* Explain why Test is disabled instead of leaving it inertly greyed. */}
          {!canTest && testStatus !== "testing" && (
            <p className="text-xs text-muted-foreground">
              Fill {missing.map((f) => f.label).join(", ")} to test the connection.
            </p>
          )}

          {testStatus === "success" && (
            <Alert className="border-green-500/50 bg-green-500/10">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              <AlertDescription className="text-green-500">
                {testMessage || "Connection successful!"}
              </AlertDescription>
            </Alert>
          )}

          {testStatus === "error" && (
            <Alert variant="destructive">
              <XCircle className="h-4 w-4" />
              <AlertDescription>
                {testMessage || "Connection failed. Please check your credentials."}
              </AlertDescription>
            </Alert>
          )}
        </div>
      )}
    </div>
  )
}
