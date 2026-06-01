"use client"

import { useState } from "react"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  FileCode, Loader2, ExternalLink, CheckCircle2,
  Database, FlaskConical, BarChart2, Code2,
} from "lucide-react"
import { serviceUrls } from "@/lib/urls"

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
  queryText: string
  columns: string[]
  rowCount: number
  executionTimeMs: number
}

function buildNotebookCells(
  queryText: string,
  columns: string[],
  rowCount: number,
  executionTimeMs: number
): object[] {
  const colPreview = columns.slice(0, 6).map(c => `"${c}"`).join(", ")
  const hasNumeric = columns.some(c =>
    /id$|count|num|amount|price|rate|score|total|sum|avg/i.test(c)
  )

  return [
    // Cell 1: Setup
    {
      cell_type: "markdown",
      source: [
        "# DataPond Analysis Notebook\n",
        "\n",
        "Generated from **SQL Lab** — edit and run to explore your data.\n",
        "\n",
        `**Query columns:** \`${columns.slice(0, 8).join(", ")}${columns.length > 8 ? " ..." : ""}\`  \n`,
        `**Rows returned:** ${rowCount.toLocaleString()}  \n`,
        `**Execution time:** ${executionTimeMs < 1000 ? `${Math.round(executionTimeMs)}ms` : `${(executionTimeMs / 1000).toFixed(2)}s`}`,
      ].join(""),
      metadata: {},
      outputs: [],
    },

    // Cell 2: Imports
    {
      cell_type: "code",
      source: [
        "import pandas as pd\n",
        "import numpy as np\n",
        "import matplotlib.pyplot as plt\n",
        "import seaborn as sns\n",
        "from trino.dbapi import connect\n",
        "import mlflow\n",
        "\n",
        "# DataPond platform connections\n",
        "TRINO_HOST  = 'trino.datapond.svc.cluster.local'\n",
        "MLFLOW_URI  = 'http://mlflow.datapond.svc.cluster.local:5000'\n",
        "\n",
        "mlflow.set_tracking_uri(MLFLOW_URI)\n",
        "print('✓ Platform connections configured')",
      ].join(""),
      metadata: {},
      outputs: [],
      execution_count: null,
    },

    // Cell 3: Load data from SQL
    {
      cell_type: "markdown",
      source: "## 1. Load Data from SQL Lab",
      metadata: {},
      outputs: [],
    },
    {
      cell_type: "code",
      source: [
        "# Connect to Trino and run the query\n",
        "conn = connect(\n",
        "    host=TRINO_HOST,\n",
        "    port=8080,\n",
        "    user='datapond',\n",
        "    catalog='iceberg',\n",
        ")\n",
        "\n",
        "SQL = \"\"\"\n",
        queryText.split("\n").map(l => `${l}\n`).join(""),
        "\"\"\"\n",
        "\n",
        "df = pd.read_sql(SQL, conn)\n",
        "print(f'Loaded {len(df):,} rows × {len(df.columns)} columns')\n",
        "df.head()",
      ].join(""),
      metadata: {},
      outputs: [],
      execution_count: null,
    },

    // Cell 4: EDA
    {
      cell_type: "markdown",
      source: "## 2. Explore the Data",
      metadata: {},
      outputs: [],
    },
    {
      cell_type: "code",
      source: [
        "# Basic statistics\n",
        "print('Shape:', df.shape)\n",
        "print('\\nData types:')\n",
        "print(df.dtypes)\n",
        "print('\\nNull counts:')\n",
        "print(df.isnull().sum())\n",
        "print('\\nNumeric summary:')\n",
        "df.describe()",
      ].join(""),
      metadata: {},
      outputs: [],
      execution_count: null,
    },

    // Cell 5: Visualization
    {
      cell_type: "code",
      source: hasNumeric ? [
        "# Quick visualization\n",
        "fig, axes = plt.subplots(1, 2, figsize=(12, 4))\n",
        "\n",
        "# Distribution of first numeric column\n",
        `numeric_cols = df.select_dtypes(include='number').columns.tolist()\n`,
        "if numeric_cols:\n",
        "    df[numeric_cols[0]].hist(ax=axes[0], bins=30, edgecolor='black', alpha=0.7)\n",
        "    axes[0].set_title(f'Distribution: {numeric_cols[0]}')\n",
        "    \n",
        "    if len(numeric_cols) >= 2:\n",
        "        df[numeric_cols[:8]].corr().pipe(\n",
        "            lambda c: sns.heatmap(c, ax=axes[1], annot=True, fmt='.2f', cmap='coolwarm')\n",
        "        )\n",
        "        axes[1].set_title('Correlation Matrix')\n",
        "\n",
        "plt.tight_layout()\n",
        "plt.show()",
      ].join("") : [
        "# Distribution of categorical columns\n",
        "cat_cols = df.select_dtypes(include='object').columns.tolist()[:4]\n",
        "if cat_cols:\n",
        "    fig, axes = plt.subplots(1, len(cat_cols), figsize=(5 * len(cat_cols), 4))\n",
        "    if len(cat_cols) == 1: axes = [axes]\n",
        "    for ax, col in zip(axes, cat_cols):\n",
        "        df[col].value_counts().head(10).plot(kind='bar', ax=ax)\n",
        "        ax.set_title(col)\n",
        "        ax.tick_params(axis='x', rotation=45)\n",
        "    plt.tight_layout()\n",
        "    plt.show()",
      ].join(""),
      metadata: {},
      outputs: [],
      execution_count: null,
    },

    // Cell 6: MLflow experiment
    {
      cell_type: "markdown",
      source: "## 3. Track with MLflow",
      metadata: {},
      outputs: [],
    },
    {
      cell_type: "code",
      source: [
        "# Set up MLflow experiment\n",
        "experiment_name = 'my-analysis'  # ← change this\n",
        "mlflow.set_experiment(experiment_name)\n",
        "\n",
        "with mlflow.start_run(run_name='exploratory-analysis'):\n",
        "    # Log data characteristics\n",
        "    mlflow.log_param('query_rows', len(df))\n",
        "    mlflow.log_param('query_cols', len(df.columns))\n",
        "    mlflow.log_param('columns', ', '.join(df.columns.tolist()[:10]))\n",
        "    \n",
        "    # Add your model training here and log metrics:\n",
        "    # mlflow.log_metric('accuracy', 0.95)\n",
        "    # mlflow.sklearn.log_model(model, 'model')\n",
        "    \n",
        "    run_id = mlflow.active_run().info.run_id\n",
        "    print(f'✓ Run logged: {run_id}')\n",
        `    print(f'  View: ${serviceUrls.mlflow()}/#/experiments')`,
      ].join(""),
      metadata: {},
      outputs: [],
      execution_count: null,
    },
  ]
}

export function OpenInNotebookModal({
  open, onOpenChange, queryText, columns, rowCount, executionTimeMs,
}: Props) {
  const [notebookName, setNotebookName] = useState(
    `analysis_${new Date().toISOString().slice(0, 10)}`
  )
  const [creating, setCreating] = useState(false)
  const [createdPath, setCreatedPath] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleCreate = async () => {
    const name = notebookName.trim().replace(/\.ipynb$/, "") + ".ipynb"
    setCreating(true)
    setError(null)

    try {
      const cells = buildNotebookCells(queryText, columns, rowCount, executionTimeMs)
      const res = await fetch(
        `/jupyter/api/contents/${encodeURIComponent(name)}?token=jupyter`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: "notebook",
            content: {
              metadata: {
                kernelspec: {
                  display_name: "Python 3 (ipykernel)",
                  language: "python",
                  name: "python3",
                },
                language_info: { name: "python" },
              },
              nbformat: 4,
              nbformat_minor: 5,
              cells,
            },
          }),
        }
      )
      if (!res.ok) throw new Error(`JupyterLab API error: ${res.status}`)
      const data = await res.json()
      setCreatedPath(data.path)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create notebook")
    } finally {
      setCreating(false)
    }
  }

  const handleOpen = () => {
    if (createdPath) {
      window.open(
        `${serviceUrls.jupyter()}/lab/tree/${encodeURIComponent(createdPath)}`,
        "_blank"
      )
    }
  }

  const handleReset = () => {
    setCreatedPath(null)
    setError(null)
  }

  const steps = [
    { icon: Database,      label: "SQL 쿼리 로드 코드 삽입" },
    { icon: BarChart2,     label: "데이터 탐색 (EDA) 코드" },
    { icon: Code2,         label: "시각화 코드 자동 생성" },
    { icon: FlaskConical,  label: "MLflow 실험 추적 설정" },
  ]

  return (
    <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); if (!v) handleReset() }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <FileCode className="h-4 w-4" />
            Open in Notebook
          </DialogTitle>
        </DialogHeader>

        {!createdPath ? (
          <>
            {/* Query preview */}
            <div className="rounded-lg border bg-muted/40 p-3 space-y-1.5">
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Database className="h-3 w-3" />
                  {rowCount.toLocaleString()} rows
                </span>
                <span className="flex items-center gap-1">
                  <BarChart2 className="h-3 w-3" />
                  {columns.length} columns
                </span>
              </div>
              <code className="text-[11px] text-muted-foreground line-clamp-2 font-mono block">
                {queryText.replace(/\s+/g, " ").trim().slice(0, 120)}
                {queryText.length > 120 ? "..." : ""}
              </code>
            </div>

            {/* What gets generated */}
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                노트북에 생성되는 내용
              </p>
              <div className="grid grid-cols-2 gap-1.5">
                {steps.map(({ icon: Icon, label }) => (
                  <div key={label} className="flex items-center gap-2 text-xs text-muted-foreground
                                              bg-muted/30 rounded-md px-2.5 py-1.5 border">
                    <Icon className="h-3 w-3 shrink-0 text-primary" />
                    {label}
                  </div>
                ))}
              </div>
            </div>

            {/* Notebook name */}
            <div className="space-y-1.5">
              <Label className="text-xs">노트북 이름</Label>
              <div className="flex items-center gap-1.5">
                <Input
                  value={notebookName}
                  onChange={e => setNotebookName(e.target.value)}
                  className="h-8 text-sm font-mono"
                  placeholder="analysis_2026-05-04"
                />
                <Badge variant="outline" className="text-[10px] shrink-0">.ipynb</Badge>
              </div>
            </div>

            {error && (
              <p className="text-xs text-destructive bg-destructive/5 rounded p-2">{error}</p>
            )}

            <DialogFooter>
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleCreate}
                disabled={creating || !notebookName.trim()}
                className="gap-1.5"
              >
                {creating
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />생성 중...</>
                  : <><FileCode className="h-3.5 w-3.5" />노트북 생성</>
                }
              </Button>
            </DialogFooter>
          </>
        ) : (
          /* Success state */
          <div className="space-y-4 py-2">
            <div className="flex flex-col items-center gap-3 py-4 text-center">
              <div className="h-12 w-12 rounded-full bg-emerald-50 flex items-center justify-center">
                <CheckCircle2 className="h-6 w-6 text-emerald-600" />
              </div>
              <div>
                <p className="font-medium text-sm">노트북이 준비됐습니다</p>
                <p className="text-xs text-muted-foreground mt-0.5 font-mono">{createdPath}</p>
              </div>
            </div>

            <div className="rounded-lg border bg-muted/30 p-3 space-y-1.5 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">다음 단계</p>
              <ol className="space-y-1 list-decimal list-inside">
                <li>JupyterLab을 열고 셀을 순서대로 실행</li>
                <li>SQL 쿼리로 DataFrame 로드 확인</li>
                <li>EDA·시각화 후 모델 학습 코드 추가</li>
                <li>MLflow로 실험 결과 자동 추적</li>
              </ol>
            </div>

            <DialogFooter className="gap-2">
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                닫기
              </Button>
              <Button size="sm" onClick={handleOpen} className="gap-1.5">
                <ExternalLink className="h-3.5 w-3.5" />
                JupyterLab에서 열기
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
