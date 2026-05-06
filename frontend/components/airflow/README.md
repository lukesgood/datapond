# Airflow Components

This directory contains React components for the Airflow integration in DataPond.

## Components

### `dag-card.tsx`
DAG card component for displaying DAG information in a grid layout.

**Props:**
- `dag_id` - DAG identifier
- `is_paused` - Whether the DAG is paused
- `description` - DAG description
- `schedule_interval` - Schedule interval (cron or preset)
- `last_run_state` - State of the last run
- `last_run_time` - Time of the last run
- `success_rate` - Success rate percentage
- `onTrigger` - Callback when trigger button is clicked
- `onTogglePause` - Callback when pause/unpause is clicked

### `dag-run-list.tsx`
List component for displaying DAG runs with status, duration, and links.

**Props:**
- `runs` - Array of DAG run objects
- `showDagId` - Whether to show the DAG ID (useful for cross-DAG run lists)

### `task-list.tsx`
List component for displaying task instances within a DAG run.

**Props:**
- `tasks` - Array of task instance objects
- `onViewLogs` - Callback when view logs button is clicked

### `dag-graph.tsx`
Visual DAG structure component using ReactFlow for graph visualization.

**Props:**
- `dag_id` - DAG identifier
- `nodes` - Array of graph nodes (tasks)
- `edges` - Array of graph edges (dependencies)

**Features:**
- Auto-layout using hierarchical algorithm
- Interactive pan/zoom
- Task dependency visualization

### `logs-viewer.tsx`
Modal component for viewing task logs with search and download.

**Props:**
- `taskId` - Task identifier
- `dagId` - DAG identifier
- `runId` - Run identifier
- `tryNumber` - Try number (default: 1)
- `isOpen` - Whether the modal is open
- `onClose` - Callback when modal is closed
- `autoRefresh` - Whether to auto-refresh logs for running tasks

**Features:**
- Search/filter logs
- Auto-refresh for running tasks
- Download logs as text file
- Terminal-style display

## Usage

```tsx
import { DagCard } from "@/components/airflow/dag-card"
import { DagRunList } from "@/components/airflow/dag-run-list"
import { TaskList } from "@/components/airflow/task-list"
import { DagGraph } from "@/components/airflow/dag-graph"
import { LogsViewer } from "@/components/airflow/logs-viewer"

// Example: DAG card
<DagCard
  dag_id="my_dag"
  is_paused={false}
  description="My ETL pipeline"
  schedule_interval="@daily"
  last_run_state="success"
  success_rate={98.5}
  onTrigger={(id) => console.log("Trigger", id)}
  onTogglePause={(id, paused) => console.log("Toggle", id, paused)}
/>

// Example: Run list
<DagRunList
  runs={dagRuns}
  showDagId={true}
/>

// Example: Task list
<TaskList
  tasks={taskInstances}
  onViewLogs={(taskId) => console.log("View logs", taskId)}
/>

// Example: DAG graph
<DagGraph
  dag_id="my_dag"
  nodes={graphNodes}
  edges={graphEdges}
/>

// Example: Logs viewer
<LogsViewer
  taskId="extract_data"
  dagId="my_dag"
  runId="run_123"
  tryNumber={1}
  isOpen={showLogs}
  onClose={() => setShowLogs(false)}
  autoRefresh={true}
/>
```

## API Integration

All components expect data from the Airflow API backend. The API endpoints are:

- `GET /api/airflow/dags` - List all DAGs
- `GET /api/airflow/dags/{dag_id}` - Get DAG details
- `PATCH /api/airflow/dags/{dag_id}` - Update DAG (pause/unpause)
- `GET /api/airflow/dags/{dag_id}/runs` - List DAG runs
- `POST /api/airflow/dags/{dag_id}/runs` - Trigger DAG
- `GET /api/airflow/runs/{run_id}` - Get run details
- `GET /api/airflow/runs/{run_id}/tasks` - List task instances
- `GET /api/airflow/tasks/{task_id}/logs` - Get task logs
- `GET /api/airflow/dags/{dag_id}/stats` - Get DAG statistics
- `GET /api/airflow/dags/{dag_id}/structure` - Get DAG graph structure

See `/backend/app/api/airflow.py` for full API documentation.
