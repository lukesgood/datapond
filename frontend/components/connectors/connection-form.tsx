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
import { Loader2, CheckCircle2, XCircle } from "lucide-react"

interface ConnectionFormProps {
  fields: ConnectorField[]
  values: Record<string, any>
  onChange: (name: string, value: any) => void
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
  return (
    <div className="space-y-6">
      <div className="grid gap-4">
        {fields.map((field) => (
          <div key={field.name} className="space-y-2">
            <Label htmlFor={field.name}>
              {field.label}
              {field.required && <span className="text-destructive ml-1">*</span>}
            </Label>

            {field.type === "textarea" ? (
              <Textarea
                id={field.name}
                placeholder={field.placeholder}
                value={values[field.name] || ""}
                onChange={(e) => onChange(field.name, e.target.value)}
                required={field.required}
                className="font-mono text-sm min-h-[180px]"
              />
            ) : field.type === "text" || field.type === "password" ? (
              <Input
                id={field.name}
                type={field.type}
                placeholder={field.placeholder}
                value={values[field.name] || ""}
                onChange={(e) => onChange(field.name, e.target.value)}
                required={field.required}
              />
            ) : field.type === "number" ? (
              <Input
                id={field.name}
                type="number"
                placeholder={field.placeholder}
                value={values[field.name] || field.default || ""}
                onChange={(e) => onChange(field.name, parseInt(e.target.value))}
                required={field.required}
              />
            ) : field.type === "boolean" ? (
              <div className="flex items-center space-x-2">
                <Switch
                  id={field.name}
                  checked={values[field.name] || field.default || false}
                  onCheckedChange={(checked) => onChange(field.name, checked)}
                />
                <Label htmlFor={field.name} className="cursor-pointer">
                  {field.help || "Enable"}
                </Label>
              </div>
            ) : field.type === "select" ? (
              <Select
                value={values[field.name] || field.default}
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
        ))}
      </div>

      {/* Test Connection */}
      {onTest && (
        <div className="space-y-2">
          <Button
            type="button"
            variant="outline"
            onClick={onTest}
            disabled={testStatus === "testing"}
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
