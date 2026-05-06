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
  { id: 1, name: "Connection Details", description: "Configure source connection" },
  { id: 2, name: "Schema Selection", description: "Choose tables to sync" },
  { id: 3, name: "Sync Configuration", description: "Set up sync schedule" }
]

// Mock table data (would come from API after test connection)
const mockTables = [
  {
    name: "users",
    schema: "public",
    row_count: 15420,
    columns: [
      { name: "id", type: "integer", nullable: false },
      { name: "email", type: "varchar(255)", nullable: false },
      { name: "created_at", type: "timestamp", nullable: false },
      { name: "updated_at", type: "timestamp", nullable: true }
    ]
  },
  {
    name: "orders",
    schema: "public",
    row_count: 48302,
    columns: [
      { name: "id", type: "integer", nullable: false },
      { name: "user_id", type: "integer", nullable: false },
      { name: "total", type: "decimal(10,2)", nullable: false },
      { name: "status", type: "varchar(50)", nullable: false },
      { name: "created_at", type: "timestamp", nullable: false }
    ]
  },
  {
    name: "products",
    schema: "public",
    row_count: 3250,
    columns: [
      { name: "id", type: "integer", nullable: false },
      { name: "name", type: "varchar(255)", nullable: false },
      { name: "price", type: "decimal(10,2)", nullable: false },
      { name: "stock", type: "integer", nullable: false }
    ]
  }
]

export default function ConnectorSetupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const connector = getConnector(id)

  const [currentStep, setCurrentStep] = useState(1)
  const [connectionName, setConnectionName] = useState(`${connector?.name} Connection`)
  const [config, setConfig] = useState<Record<string, any>>({})
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle")
  const [testMessage, setTestMessage] = useState("")
  const [selectedTables, setSelectedTables] = useState<string[]>([])
  const [availableTables, setAvailableTables] = useState(mockTables)
  const [loadingTables, setLoadingTables] = useState(false)
  const [syncMode, setSyncMode] = useState("incremental")
  const [syncFrequency, setSyncFrequency] = useState("daily")
  const [creating, setCreating] = useState(false)

  if (!connector) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <h2 className="text-2xl font-bold">Connector not found</h2>
          <p className="text-muted-foreground mt-2">The requested connector does not exist.</p>
          <Link href="/connectors">
            <Button className="mt-4">Back to Marketplace</Button>
          </Link>
        </div>
      </div>
    )
  }

  const handleConfigChange = (name: string, value: any) => {
    setConfig(prev => ({ ...prev, [name]: value }))
  }

  const handleTestConnection = async () => {
    setTestStatus("testing")
    setTestMessage("")
    try {
      const res = await fetch("/api/connectors/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector_type: id,
          config,
        }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setTestStatus("success")
        setTestMessage(data.message || "Connection successful!")
        // Attempt to fetch real table list after successful test
        setLoadingTables(true)
        try {
          const connRes = await fetch("/api/connectors/connections")
          // We don't have an ID yet (not created), so use mock tables as fallback
          // Real table fetch happens after connection is created
        } finally {
          setLoadingTables(false)
        }
      } else {
        setTestStatus("error")
        setTestMessage(data.detail || data.message || "Connection failed")
      }
    } catch (e) {
      setTestStatus("error")
      setTestMessage(e instanceof Error ? e.message : "Connection failed")
    }
  }

  const handleTableToggle = (tableName: string) => {
    setSelectedTables(prev =>
      prev.includes(tableName)
        ? prev.filter(t => t !== tableName)
        : [...prev, tableName]
    )
  }

  const handleToggleAll = (selected: boolean) => {
    setSelectedTables(selected ? availableTables.map(t => t.name) : [])
  }

  const handleCreateConnection = async () => {
    setCreating(true)
    try {
      const res = await fetch("/api/connectors/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: connectionName,
          connector_type: id,
          config: {
            ...config,
            selected_tables: selectedTables,
            sync_mode: syncMode,
            sync_frequency: syncFrequency,
          },
        }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || "Failed to create connection")
      }
      router.push("/connectors")
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to create connection")
      setCreating(false)
    }
  }

  const canProceed = () => {
    if (currentStep === 1) {
      return testStatus === "success"
    }
    if (currentStep === 2) {
      return selectedTables.length > 0
    }
    return true
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/connectors">
          <Button variant="ghost" size="icon">
            <ChevronLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Set up {connector.name}</h2>
          <p className="text-muted-foreground">{connector.description}</p>
        </div>
      </div>

      {/* Progress Steps */}
      <div className="flex items-center justify-between max-w-3xl mx-auto">
        {STEPS.map((step, index) => (
          <div key={step.id} className="flex items-center flex-1">
            <div className="flex flex-col items-center flex-1">
              <div
                className={`flex h-10 w-10 items-center justify-center rounded-full border-2 ${
                  currentStep >= step.id
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-muted-foreground/30 text-muted-foreground"
                }`}
              >
                {currentStep > step.id ? (
                  <CheckCircle2 className="h-5 w-5" />
                ) : (
                  <span>{step.id}</span>
                )}
              </div>
              <div className="mt-2 text-center">
                <p className={`text-sm font-medium ${currentStep >= step.id ? "" : "text-muted-foreground"}`}>
                  {step.name}
                </p>
                <p className="text-xs text-muted-foreground hidden sm:block">{step.description}</p>
              </div>
            </div>
            {index < STEPS.length - 1 && (
              <div
                className={`h-0.5 flex-1 mx-4 ${
                  currentStep > step.id ? "bg-primary" : "bg-muted-foreground/30"
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step Content */}
      <Card className="max-w-3xl mx-auto">
        <CardHeader>
          <CardTitle>{STEPS[currentStep - 1].name}</CardTitle>
          <CardDescription>{STEPS[currentStep - 1].description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Step 1: Connection Details */}
          {currentStep === 1 && (
            <div className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="connection-name">Connection Name</Label>
                <Input
                  id="connection-name"
                  value={connectionName}
                  onChange={(e) => setConnectionName(e.target.value)}
                  placeholder="My Database Connection"
                />
              </div>

              <ConnectionForm
                fields={connector.fields}
                values={config}
                onChange={handleConfigChange}
                onTest={handleTestConnection}
                testStatus={testStatus}
                testMessage={testMessage}
              />
            </div>
          )}

          {/* Step 2: Schema Selection */}
          {currentStep === 2 && (
            <TableSelector
              tables={availableTables}
              selectedTables={selectedTables}
              onToggle={handleTableToggle}
              onToggleAll={handleToggleAll}
            />
          )}

          {/* Step 3: Sync Configuration */}
          {currentStep === 3 && (
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="sync-mode">Sync Mode</Label>
                  <Select value={syncMode} onValueChange={(value) => setSyncMode(value || "incremental")}>
                    <SelectTrigger id="sync-mode">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="full">Full Refresh</SelectItem>
                      <SelectItem value="incremental">Incremental</SelectItem>
                      <SelectItem value="cdc">Change Data Capture (CDC)</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    {syncMode === "full" && "Replaces all data on each sync"}
                    {syncMode === "incremental" && "Only syncs new or modified records"}
                    {syncMode === "cdc" && "Real-time streaming of database changes"}
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="sync-frequency">Sync Frequency</Label>
                  <Select value={syncFrequency} onValueChange={(value) => setSyncFrequency(value || "daily")}>
                    <SelectTrigger id="sync-frequency">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="manual">Manual</SelectItem>
                      <SelectItem value="hourly">Every Hour</SelectItem>
                      <SelectItem value="daily">Daily</SelectItem>
                      <SelectItem value="weekly">Weekly</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="border rounded-lg p-4 space-y-2">
                <h4 className="font-medium">Summary</h4>
                <div className="space-y-1 text-sm text-muted-foreground">
                  <p>Connection: <span className="text-foreground">{connectionName}</span></p>
                  <p>Connector: <span className="text-foreground">{connector.name}</span></p>
                  <p>Tables: <span className="text-foreground">{selectedTables.length} selected</span></p>
                  <p>Sync Mode: <span className="text-foreground capitalize">{syncMode}</span></p>
                  <p>Frequency: <span className="text-foreground capitalize">{syncFrequency}</span></p>
                </div>
              </div>
            </div>
          )}

          {/* Navigation Buttons */}
          <div className="flex justify-between pt-4">
            <Button
              variant="outline"
              onClick={() => setCurrentStep(prev => prev - 1)}
              disabled={currentStep === 1 || creating}
            >
              <ChevronLeft className="h-4 w-4 mr-2" />
              Previous
            </Button>

            {currentStep < 3 ? (
              <Button
                onClick={() => setCurrentStep(prev => prev + 1)}
                disabled={!canProceed()}
              >
                Next
                <ChevronRight className="h-4 w-4 ml-2" />
              </Button>
            ) : (
              <Button onClick={handleCreateConnection} disabled={creating}>
                {creating && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Create Connection
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
