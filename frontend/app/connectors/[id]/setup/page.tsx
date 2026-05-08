"use client"

import { useState, use } from "react"
import { useRouter } from "next/navigation"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { ConnectionForm } from "@/components/connectors/connection-form"
import { TableSelector } from "@/components/connectors/table-selector"
import { getConnector } from "@/lib/connectors"
import { ChevronLeft, ChevronRight, Loader2, CheckCircle2 } from "lucide-react"
import Link from "next/link"

const STEPS = [
  { id: 1, name: "Connection",  description: "Configure source connection" },
  { id: 2, name: "Tables",      description: "Choose tables to sync" },
  { id: 3, name: "Schedule",    description: "Set up sync schedule" },
]

const mockTables = [
  {
    name: "users", schema: "public", row_count: 15420,
    columns: [
      { name: "id", type: "integer", nullable: false },
      { name: "email", type: "varchar(255)", nullable: false },
      { name: "created_at", type: "timestamp", nullable: false },
    ]
  },
  {
    name: "orders", schema: "public", row_count: 48302,
    columns: [
      { name: "id", type: "integer", nullable: false },
      { name: "user_id", type: "integer", nullable: false },
      { name: "total", type: "decimal(10,2)", nullable: false },
      { name: "status", type: "varchar(50)", nullable: false },
    ]
  },
  {
    name: "products", schema: "public", row_count: 3250,
    columns: [
      { name: "id", type: "integer", nullable: false },
      { name: "name", type: "varchar(255)", nullable: false },
      { name: "price", type: "decimal(10,2)", nullable: false },
    ]
  },
]

export default function ConnectorSetupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const connector = getConnector(id)

  const [currentStep, setCurrentStep]       = useState(1)
  const [connectionName, setConnectionName] = useState(`${connector?.name || ""} Connection`)
  // Pre-populate defaults from connector field definitions
  const [config, setConfig] = useState<Record<string, any>>(() => {
    const defaults: Record<string, any> = {}
    connector?.fields.forEach(f => {
      if (f.default !== undefined) defaults[f.name] = f.default
    })
    return defaults
  })
  const [testStatus, setTestStatus]         = useState<"idle" | "testing" | "success" | "error">("idle")
  const [testMessage, setTestMessage]       = useState("")
  const [selectedTables, setSelectedTables] = useState<string[]>([])
  const [availableTables]                   = useState(mockTables)
  const [syncMode, setSyncMode]             = useState("incremental")
  const [syncFrequency, setSyncFrequency]   = useState("daily")
  const [creating, setCreating]             = useState(false)

  if (!connector) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <h2 className="text-2xl font-bold">Connector not found</h2>
          <p className="text-muted-foreground mt-2">The requested connector does not exist.</p>
          <Link href="/connectors"><Button className="mt-4">Back to Marketplace</Button></Link>
        </div>
      </div>
    )
  }

  const handleTestConnection = async () => {
    setTestStatus("testing"); setTestMessage("")
    try {
      const res = await fetch("/api/connectors/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_type: id, config }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setTestStatus("success")
        setTestMessage(data.message || "Connection successful!")
      } else {
        setTestStatus("error")
        setTestMessage(data.detail || data.message || "Connection failed")
      }
    } catch (e) {
      setTestStatus("error")
      setTestMessage(e instanceof Error ? e.message : "Connection failed")
    }
  }

  // Map UI frequency labels to cron expressions
  const FREQUENCY_TO_CRON: Record<string, string> = {
    hourly:  "0 * * * *",
    daily:   "0 2 * * *",
    weekly:  "0 2 * * 1",
  }

  const handleCreateConnection = async () => {
    setCreating(true)
    try {
      // 1. Create the connection
      const res = await fetch("/api/connectors/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: connectionName,
          connector_type: id,
          config: { ...config, selected_tables: selectedTables, sync_mode: syncMode },
        }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || "Failed to create connection")
      }
      const created = await res.json()

      // 2. Apply schedule if not manual
      const cron = FREQUENCY_TO_CRON[syncFrequency]
      if (cron && created.id) {
        await fetch(`/api/connectors/${created.id}/schedule`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ schedule: cron }),
        })
      }

      // 3. Navigate to the new connection detail page
      router.push(created.id ? `/connectors/connections/${created.id}` : "/connectors")
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to create connection")
      setCreating(false)
    }
  }

  const canProceed = () => {
    if (currentStep === 1) return testStatus === "success"
    if (currentStep === 2) return selectedTables.length > 0
    return true
  }

  return (
    // ── Outer: full height, scrollable ────────────────────────────────────────
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-center gap-3">
          <Link href="/connectors">
            <Button variant="ghost" size="icon" className="shrink-0">
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div className="min-w-0">
            <h2 className="text-xl font-bold truncate">Set up {connector.name}</h2>
            <p className="text-sm text-muted-foreground truncate">{connector.description}</p>
          </div>
        </div>

        {/* Progress Steps — compact, no overflow */}
        <div className="flex items-center">
          {STEPS.map((step, index) => (
            <div key={step.id} className="flex items-center flex-1 min-w-0">
              <div className="flex items-center gap-2 shrink-0">
                <div className={`flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-medium shrink-0 ${
                  currentStep > step.id
                    ? "border-primary bg-primary text-primary-foreground"
                    : currentStep === step.id
                      ? "border-primary text-primary"
                      : "border-muted-foreground/30 text-muted-foreground"
                }`}>
                  {currentStep > step.id ? <CheckCircle2 className="h-4 w-4" /> : step.id}
                </div>
                <span className={`text-sm font-medium hidden sm:block ${
                  currentStep >= step.id ? "text-foreground" : "text-muted-foreground"
                }`}>{step.name}</span>
              </div>
              {index < STEPS.length - 1 && (
                <div className={`flex-1 h-0.5 mx-2 ${currentStep > step.id ? "bg-primary" : "bg-muted-foreground/20"}`} />
              )}
            </div>
          ))}
        </div>

        {/* Step Content Card */}
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base">{STEPS[currentStep - 1].name}</CardTitle>
            <CardDescription>{STEPS[currentStep - 1].description}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">

            {/* Step 1: Connection Details */}
            {currentStep === 1 && (
              <div className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="connection-name">Connection Name</Label>
                  <Input
                    id="connection-name"
                    value={connectionName}
                    onChange={e => setConnectionName(e.target.value)}
                    placeholder="My Database Connection"
                  />
                </div>
                <ConnectionForm
                  fields={connector.fields}
                  values={config}
                  onChange={(name, value) => {
                    setConfig(prev => ({ ...prev, [name]: value }))
                    // Reset test result when any field changes
                    if (testStatus !== "idle") {
                      setTestStatus("idle")
                      setTestMessage("")
                    }
                  }}
                  onTest={handleTestConnection}
                  testStatus={testStatus}
                  testMessage={testMessage}
                />
              </div>
            )}

            {/* Step 2: Table Selection */}
            {currentStep === 2 && (
              <TableSelector
                tables={availableTables}
                selectedTables={selectedTables}
                onToggle={name => setSelectedTables(prev =>
                  prev.includes(name) ? prev.filter(t => t !== name) : [...prev, name]
                )}
                onToggleAll={all => setSelectedTables(all ? availableTables.map(t => t.name) : [])}
              />
            )}

            {/* Step 3: Sync Configuration */}
            {currentStep === 3 && (
              <div className="space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label>Sync Mode</Label>
                    <Select value={syncMode} onValueChange={v => setSyncMode(v || "incremental")}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="full">Full Refresh</SelectItem>
                        <SelectItem value="incremental">Incremental</SelectItem>
                        <SelectItem value="cdc">Change Data Capture</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {syncMode === "full" && "Replaces all data on each sync"}
                      {syncMode === "incremental" && "Only syncs new or modified records"}
                      {syncMode === "cdc" && "Real-time streaming of database changes"}
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>Schedule</Label>
                    <Select value={syncFrequency} onValueChange={v => setSyncFrequency(v || "daily")}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="manual">Manual only</SelectItem>
                        <SelectItem value="hourly">Every Hour (0 * * * *)</SelectItem>
                        <SelectItem value="daily">Daily at 2am (0 2 * * *)</SelectItem>
                        <SelectItem value="weekly">Weekly Mon 2am (0 2 * * 1)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {syncFrequency === "manual"
                        ? "Sync manually from the connection page"
                        : `Airflow DAG will be created automatically`}
                    </p>
                  </div>
                </div>

                {/* Summary */}
                <div className="rounded-lg border bg-muted/30 p-4 space-y-2 text-sm">
                  <p className="font-medium text-xs uppercase tracking-wide text-muted-foreground mb-3">Summary</p>
                  {[
                    ["Connection", connectionName],
                    ["Connector",  connector.name],
                    ["Tables",     `${selectedTables.length} selected`],
                    ["Sync Mode",  syncMode],
                    ["Schedule",   syncFrequency === "manual"
                      ? "Manual"
                      : `${syncFrequency} (${FREQUENCY_TO_CRON[syncFrequency]})`],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-muted-foreground">{label}</span>
                      <span className="font-medium capitalize">{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Navigation */}
            <div className="flex items-center justify-between pt-2 border-t">
              <Button
                variant="outline" size="sm"
                onClick={() => setCurrentStep(p => p - 1)}
                disabled={currentStep === 1 || creating}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />Back
              </Button>

              {/* Step indicator (mobile) */}
              <span className="text-xs text-muted-foreground sm:hidden">
                {currentStep} / {STEPS.length}
              </span>

              {currentStep < 3 ? (
                <Button size="sm" onClick={() => setCurrentStep(p => p + 1)} disabled={!canProceed()}>
                  Next<ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              ) : (
                <Button size="sm" onClick={handleCreateConnection} disabled={creating}>
                  {creating && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                  Create Connection
                </Button>
              )}
            </div>

          </CardContent>
        </Card>
      </div>
    </div>
  )
}
