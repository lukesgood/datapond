# DataPond 관리 UI 개선 가이드

**버전**: 2.1.0  
**작성일**: 2026-04-28  
**대상**: 플랫폼 관리자, DevOps, SRE

---

## 📋 Executive Summary

현재 DataPond는 **관리자 UI가 전무**한 상태입니다. 프로덕션 환경에서 플랫폼을 안정적으로 운영하기 위해서는 포괄적인 관리 대시보드가 필수입니다.

### 관리 UI 현황: 0/100

| 영역 | 현재 상태 | 필요성 |
|------|-----------|--------|
| 사용자 관리 | ❌ 없음 | 🔴 Critical |
| 리소스 관리 | ❌ 없음 | 🔴 Critical |
| 시스템 모니터링 | ❌ 없음 | 🔴 Critical |
| 보안/감사 | ❌ 없음 | 🔴 Critical |
| 비용 관리 | ❌ 없음 | 🔴 Critical |
| 데이터 거버넌스 | ❌ 없음 | 🟡 High |
| 백업/복구 | ❌ 없음 | 🔴 Critical |
| 알림 설정 | ❌ 없음 | 🟡 High |

---

## 🎯 관리 UI 구조

### 메인 네비게이션

```typescript
const ADMIN_NAVIGATION = [
  {
    section: "Users & Access",
    icon: Users,
    items: [
      { label: "Users", path: "/admin/users", icon: User },
      { label: "Teams", path: "/admin/teams", icon: Users },
      { label: "Roles & Permissions", path: "/admin/roles", icon: Shield },
      { label: "API Keys", path: "/admin/api-keys", icon: Key },
      { label: "SSO Configuration", path: "/admin/sso", icon: Lock },
    ]
  },
  {
    section: "System",
    icon: Server,
    items: [
      { label: "Dashboard", path: "/admin", icon: LayoutDashboard },
      { label: "Resource Usage", path: "/admin/resources", icon: Cpu },
      { label: "Monitoring", path: "/admin/monitoring", icon: Activity },
      { label: "Audit Logs", path: "/admin/audit", icon: FileText },
      { label: "Health Checks", path: "/admin/health", icon: Heart },
    ]
  },
  {
    section: "Data",
    icon: Database,
    items: [
      { label: "Data Sources", path: "/admin/data-sources", icon: Database },
      { label: "Data Catalog", path: "/admin/catalog", icon: BookOpen },
      { label: "Data Quality", path: "/admin/quality", icon: CheckCircle },
      { label: "Lineage", path: "/admin/lineage", icon: GitBranch },
    ]
  },
  {
    section: "Cost & Billing",
    icon: DollarSign,
    items: [
      { label: "Usage & Billing", path: "/admin/billing", icon: DollarSign },
      { label: "Budgets & Alerts", path: "/admin/budgets", icon: AlertCircle },
      { label: "Cost Analysis", path: "/admin/cost-analysis", icon: TrendingUp },
      { label: "Resource Optimization", path: "/admin/optimization", icon: Zap },
    ]
  },
  {
    section: "Configuration",
    icon: Settings,
    items: [
      { label: "General Settings", path: "/admin/settings", icon: Settings },
      { label: "Integrations", path: "/admin/integrations", icon: Plug },
      { label: "Notifications", path: "/admin/notifications", icon: Bell },
      { label: "Backup & Restore", path: "/admin/backup", icon: Download },
      { label: "Security", path: "/admin/security", icon: Shield },
    ]
  },
]
```

---

## 🔴 Critical: 사용자 관리

### 1. 사용자 목록 및 관리

```typescript
// frontend/app/admin/users/page.tsx
"use client"

import { useState } from "react"
import { AdminLayout } from "@/components/layout/admin-layout"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Search, UserPlus, MoreVertical, Mail, Ban, Trash2 } from "lucide-react"
import { useUsers } from "@/lib/hooks/use-users"

export default function UsersPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedUser, setSelectedUser] = useState<any>(null)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const { data: users = [], isLoading } = useUsers()

  const filteredUsers = users.filter((user: any) =>
    user.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
    user.username.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case "admin": return "destructive"
      case "developer": return "default"
      case "analyst": return "secondary"
      default: return "outline"
    }
  }

  return (
    <AdminLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">User Management</h1>
            <p className="text-muted-foreground">
              Manage users, roles, and permissions
            </p>
          </div>
          <Button onClick={() => setShowCreateDialog(true)}>
            <UserPlus className="mr-2 h-4 w-4" />
            Add User
          </Button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold">{users.length}</div>
              <p className="text-xs text-muted-foreground">Total Users</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold">
                {users.filter((u: any) => u.status === "active").length}
              </div>
              <p className="text-xs text-muted-foreground">Active Users</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold">
                {users.filter((u: any) => u.last_login > Date.now() - 86400000).length}
              </div>
              <p className="text-xs text-muted-foreground">Active Today</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="text-2xl font-bold">
                {users.filter((u: any) => u.role === "admin").length}
              </div>
              <p className="text-xs text-muted-foreground">Admins</p>
            </CardContent>
          </Card>
        </div>

        {/* Search & Filter */}
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center space-x-2">
              <Search className="h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by email or username..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="max-w-sm"
              />
            </div>
          </CardContent>
        </Card>

        {/* Users Table */}
        <Card>
          <CardHeader>
            <CardTitle>Users ({filteredUsers.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Persona</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Login</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredUsers.map((user: any) => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center space-x-2">
                        <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                          {user.username.charAt(0).toUpperCase()}
                        </div>
                        <span>{user.username}</span>
                      </div>
                    </TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>
                      <Badge variant={getRoleBadgeColor(user.role)}>
                        {user.role}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{user.persona || "Not set"}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={user.status === "active" ? "default" : "secondary"}
                      >
                        {user.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {user.last_login
                        ? new Date(user.last_login).toLocaleDateString()
                        : "Never"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {new Date(user.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon">
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => setSelectedUser(user)}>
                            <Mail className="mr-2 h-4 w-4" />
                            Edit User
                          </DropdownMenuItem>
                          <DropdownMenuItem>
                            <Ban className="mr-2 h-4 w-4" />
                            {user.status === "active" ? "Suspend" : "Activate"}
                          </DropdownMenuItem>
                          <DropdownMenuItem className="text-destructive">
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete User
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {/* Create User Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New User</DialogTitle>
            <DialogDescription>
              Create a new user account and assign roles
            </DialogDescription>
          </DialogHeader>
          <CreateUserForm onComplete={() => setShowCreateDialog(false)} />
        </DialogContent>
      </Dialog>
    </AdminLayout>
  )
}
```

### 2. 역할 및 권한 관리

```typescript
// frontend/app/admin/roles/page.tsx
export default function RolesPage() {
  const roles = [
    {
      name: "Admin",
      description: "Full system access",
      userCount: 3,
      permissions: ["*"]
    },
    {
      name: "Developer",
      description: "Read/write data, create pipelines",
      userCount: 12,
      permissions: [
        "read_data", "write_data", "create_pipeline", 
        "execute_query", "create_notebook"
      ]
    },
    {
      name: "Analyst",
      description: "Read data, execute queries",
      userCount: 25,
      permissions: ["read_data", "execute_query", "create_notebook"]
    },
    {
      name: "Viewer",
      description: "Read-only access",
      userCount: 50,
      permissions: ["read_data"]
    }
  ]

  return (
    <AdminLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Roles & Permissions</h1>
            <p className="text-muted-foreground">
              Manage user roles and their permissions
            </p>
          </div>
          <Button>
            <Plus className="mr-2 h-4 w-4" />
            Create Role
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-6">
          {roles.map((role) => (
            <Card key={role.name}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>{role.name}</CardTitle>
                    <CardDescription>{role.description}</CardDescription>
                  </div>
                  <Badge variant="outline">{role.userCount} users</Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div>
                    <p className="text-sm font-medium mb-2">Permissions</p>
                    <div className="flex flex-wrap gap-2">
                      {role.permissions.map((perm) => (
                        <Badge key={perm} variant="secondary">
                          {perm}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex space-x-2">
                    <Button variant="outline" size="sm" className="flex-1">
                      Edit
                    </Button>
                    <Button variant="ghost" size="sm" className="flex-1">
                      View Users
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </AdminLayout>
  )
}
```

---

## 🔴 Critical: 시스템 모니터링

### 1. 관리자 대시보드

```typescript
// frontend/app/admin/page.tsx
export default function AdminDashboard() {
  const { data: systemStats } = useSystemStats()

  return (
    <AdminLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">System Overview</h1>
          <p className="text-muted-foreground">
            Monitor platform health and performance
          </p>
        </div>

        {/* System Health */}
        <div className="grid grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">System Health</p>
                  <p className="text-2xl font-bold text-green-600">Healthy</p>
                </div>
                <Heart className="h-8 w-8 text-green-600" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Active Users</p>
                  <p className="text-2xl font-bold">87</p>
                </div>
                <Users className="h-8 w-8 text-blue-600" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Running Jobs</p>
                  <p className="text-2xl font-bold">12</p>
                </div>
                <Activity className="h-8 w-8 text-purple-600" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Alerts</p>
                  <p className="text-2xl font-bold text-red-600">3</p>
                </div>
                <AlertCircle className="h-8 w-8 text-red-600" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Resource Usage */}
        <Card>
          <CardHeader>
            <CardTitle>Resource Usage</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">CPU Usage</span>
                  <span className="font-medium">65%</span>
                </div>
                <Progress value={65} className="h-2" />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Memory Usage</span>
                  <span className="font-medium">78%</span>
                </div>
                <Progress value={78} className="h-2" />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Storage Usage</span>
                  <span className="font-medium">45%</span>
                </div>
                <Progress value={45} className="h-2" />
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Network I/O</span>
                  <span className="font-medium">320 MB/s</span>
                </div>
                <Progress value={32} className="h-2" />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Service Status */}
        <Card>
          <CardHeader>
            <CardTitle>Service Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {[
                { name: "Backend API", status: "healthy", uptime: "99.98%" },
                { name: "Frontend", status: "healthy", uptime: "99.95%" },
                { name: "PostgreSQL", status: "healthy", uptime: "100%" },
                { name: "Redis", status: "healthy", uptime: "99.99%" },
                { name: "JupyterLab", status: "healthy", uptime: "99.92%" },
                { name: "MLflow", status: "degraded", uptime: "98.50%" },
                { name: "Airflow", status: "healthy", uptime: "99.87%" },
                { name: "Spark", status: "healthy", uptime: "99.65%" },
                { name: "Trino", status: "healthy", uptime: "99.91%" },
              ].map((service) => (
                <div
                  key={service.name}
                  className="flex items-center justify-between p-3 border rounded-lg"
                >
                  <div className="flex items-center space-x-3">
                    <div
                      className={`h-2 w-2 rounded-full ${
                        service.status === "healthy"
                          ? "bg-green-500"
                          : "bg-yellow-500"
                      }`}
                    />
                    <span className="font-medium">{service.name}</span>
                  </div>
                  <div className="flex items-center space-x-4">
                    <Badge
                      variant={
                        service.status === "healthy" ? "default" : "secondary"
                      }
                    >
                      {service.status}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {service.uptime} uptime
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Recent Activity */}
        <div className="grid grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Recent Alerts</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {[
                  {
                    type: "warning",
                    message: "High memory usage on spark-worker-2",
                    time: "5 minutes ago",
                  },
                  {
                    type: "error",
                    message: "MLflow service degraded",
                    time: "15 minutes ago",
                  },
                  {
                    type: "info",
                    message: "Backup completed successfully",
                    time: "1 hour ago",
                  },
                ].map((alert, i) => (
                  <div key={i} className="flex items-start space-x-3">
                    <AlertCircle
                      className={`h-4 w-4 mt-0.5 ${
                        alert.type === "error"
                          ? "text-red-600"
                          : alert.type === "warning"
                          ? "text-yellow-600"
                          : "text-blue-600"
                      }`}
                    />
                    <div className="flex-1">
                      <p className="text-sm">{alert.message}</p>
                      <p className="text-xs text-muted-foreground">
                        {alert.time}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent Admin Actions</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {[
                  {
                    user: "admin@datapond.com",
                    action: "Created user john.doe@company.com",
                    time: "10 minutes ago",
                  },
                  {
                    user: "admin@datapond.com",
                    action: "Updated role permissions for Developer",
                    time: "1 hour ago",
                  },
                  {
                    user: "admin@datapond.com",
                    action: "Triggered manual backup",
                    time: "2 hours ago",
                  },
                ].map((action, i) => (
                  <div key={i} className="text-sm">
                    <p className="font-medium">{action.action}</p>
                    <p className="text-muted-foreground">
                      by {action.user} • {action.time}
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </AdminLayout>
  )
}
```

### 2. 리소스 사용량 모니터링

```typescript
// frontend/app/admin/resources/page.tsx
export default function ResourcesPage() {
  return (
    <AdminLayout>
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">Resource Usage</h1>

        {/* Cluster Resources */}
        <Card>
          <CardHeader>
            <CardTitle>Kubernetes Cluster</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-6">
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Nodes</p>
                <p className="text-2xl font-bold">5</p>
                <p className="text-xs text-muted-foreground">
                  3 workers, 2 masters
                </p>
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Pods</p>
                <p className="text-2xl font-bold">47 / 110</p>
                <Progress value={43} className="h-2" />
              </div>
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">PVCs</p>
                <p className="text-2xl font-bold">12 / 50</p>
                <Progress value={24} className="h-2" />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Per-Service Resources */}
        <Card>
          <CardHeader>
            <CardTitle>Service Resource Allocation</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Service</TableHead>
                  <TableHead>Replicas</TableHead>
                  <TableHead>CPU Request</TableHead>
                  <TableHead>CPU Limit</TableHead>
                  <TableHead>Memory Request</TableHead>
                  <TableHead>Memory Limit</TableHead>
                  <TableHead>Storage</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[
                  {
                    name: "Backend",
                    replicas: 2,
                    cpuReq: "500m",
                    cpuLimit: "1000m",
                    memReq: "512Mi",
                    memLimit: "1Gi",
                    storage: "-",
                  },
                  {
                    name: "PostgreSQL",
                    replicas: 1,
                    cpuReq: "1000m",
                    cpuLimit: "2000m",
                    memReq: "2Gi",
                    memLimit: "4Gi",
                    storage: "50Gi",
                  },
                  // ... more services
                ].map((service) => (
                  <TableRow key={service.name}>
                    <TableCell className="font-medium">{service.name}</TableCell>
                    <TableCell>{service.replicas}</TableCell>
                    <TableCell>{service.cpuReq}</TableCell>
                    <TableCell>{service.cpuLimit}</TableCell>
                    <TableCell>{service.memReq}</TableCell>
                    <TableCell>{service.memLimit}</TableCell>
                    <TableCell>{service.storage}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Top Resource Consumers */}
        <Card>
          <CardHeader>
            <CardTitle>Top Resource Consumers (Last 24h)</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="cpu">
              <TabsList>
                <TabsTrigger value="cpu">CPU</TabsTrigger>
                <TabsTrigger value="memory">Memory</TabsTrigger>
                <TabsTrigger value="storage">Storage</TabsTrigger>
              </TabsList>
              <TabsContent value="cpu">
                <div className="space-y-2">
                  {[
                    { user: "john.doe@company.com", usage: "45.2 CPU hours" },
                    { user: "jane.smith@company.com", usage: "38.7 CPU hours" },
                    { user: "bob.wilson@company.com", usage: "32.1 CPU hours" },
                  ].map((item) => (
                    <div
                      key={item.user}
                      className="flex items-center justify-between p-2 border rounded"
                    >
                      <span className="text-sm">{item.user}</span>
                      <Badge variant="outline">{item.usage}</Badge>
                    </div>
                  ))}
                </div>
              </TabsContent>
              {/* Similar for memory and storage */}
            </Tabs>
          </CardContent>
        </Card>
      </div>
    </AdminLayout>
  )
}
```

---

## 🔴 Critical: 감사 로그

```typescript
// frontend/app/admin/audit/page.tsx
export default function AuditLogsPage() {
  const [filters, setFilters] = useState({
    user: "",
    action: "",
    resource: "",
    dateFrom: "",
    dateTo: "",
  })

  return (
    <AdminLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Audit Logs</h1>
          <p className="text-muted-foreground">
            Track all system activities and user actions
          </p>
        </div>

        {/* Filters */}
        <Card>
          <CardContent className="pt-6">
            <div className="grid grid-cols-5 gap-4">
              <Input placeholder="User email..." />
              <Select>
                <SelectTrigger>
                  <SelectValue placeholder="Action type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="create">Create</SelectItem>
                  <SelectItem value="update">Update</SelectItem>
                  <SelectItem value="delete">Delete</SelectItem>
                  <SelectItem value="execute">Execute</SelectItem>
                </SelectContent>
              </Select>
              <Select>
                <SelectTrigger>
                  <SelectValue placeholder="Resource type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">User</SelectItem>
                  <SelectItem value="query">Query</SelectItem>
                  <SelectItem value="notebook">Notebook</SelectItem>
                  <SelectItem value="workflow">Workflow</SelectItem>
                </SelectContent>
              </Select>
              <Input type="date" placeholder="From date" />
              <Input type="date" placeholder="To date" />
            </div>
          </CardContent>
        </Card>

        {/* Audit Log Table */}
        <Card>
          <CardContent className="pt-6">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>IP Address</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[
                  {
                    timestamp: new Date(),
                    user: "john.doe@company.com",
                    action: "EXECUTE_QUERY",
                    resource: "SQL Query",
                    ip: "192.168.1.100",
                    status: "success",
                    details: "SELECT * FROM users LIMIT 100",
                  },
                  {
                    timestamp: new Date(Date.now() - 300000),
                    user: "admin@datapond.com",
                    action: "CREATE_USER",
                    resource: "User",
                    ip: "192.168.1.10",
                    status: "success",
                    details: "Created user jane.smith@company.com",
                  },
                  {
                    timestamp: new Date(Date.now() - 600000),
                    user: "bob.wilson@company.com",
                    action: "DELETE_NOTEBOOK",
                    resource: "Notebook",
                    ip: "192.168.1.150",
                    status: "failed",
                    details: "Permission denied",
                  },
                ].map((log, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-sm">
                      {log.timestamp.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-sm">{log.user}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{log.action}</Badge>
                    </TableCell>
                    <TableCell className="text-sm">{log.resource}</TableCell>
                    <TableCell className="text-sm font-mono">{log.ip}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          log.status === "success" ? "default" : "destructive"
                        }
                      >
                        {log.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground max-w-xs truncate">
                      {log.details}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Export Options */}
        <div className="flex justify-end space-x-2">
          <Button variant="outline">
            <Download className="mr-2 h-4 w-4" />
            Export CSV
          </Button>
          <Button variant="outline">
            <FileText className="mr-2 h-4 w-4" />
            Export JSON
          </Button>
        </div>
      </div>
    </AdminLayout>
  )
}
```

---

## 🔴 Critical: 비용 관리

```typescript
// frontend/app/admin/billing/page.tsx
export default function BillingPage() {
  const currentMonth = {
    compute: 1250.43,
    storage: 180.25,
    network: 65.80,
    total: 1496.48,
    budget: 2000.00,
  }

  return (
    <AdminLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Usage & Billing</h1>
          <p className="text-muted-foreground">
            Monitor costs and optimize resource usage
          </p>
        </div>

        {/* Current Month Summary */}
        <div className="grid grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Total Cost (MTD)</p>
              <p className="text-3xl font-bold">${currentMonth.total.toFixed(2)}</p>
              <Progress
                value={(currentMonth.total / currentMonth.budget) * 100}
                className="mt-2"
              />
              <p className="text-xs text-muted-foreground mt-1">
                ${currentMonth.total.toFixed(2)} / ${currentMonth.budget.toFixed(2)} budget
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Compute</p>
              <p className="text-3xl font-bold">${currentMonth.compute.toFixed(2)}</p>
              <p className="text-xs text-green-600 mt-1">-5.2% vs last month</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Storage</p>
              <p className="text-3xl font-bold">${currentMonth.storage.toFixed(2)}</p>
              <p className="text-xs text-red-600 mt-1">+12.3% vs last month</p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Network</p>
              <p className="text-3xl font-bold">${currentMonth.network.toFixed(2)}</p>
              <p className="text-xs text-muted-foreground mt-1">Stable</p>
            </CardContent>
          </Card>
        </div>

        {/* Cost Trend Chart */}
        <Card>
          <CardHeader>
            <CardTitle>Cost Trend (Last 6 Months)</CardTitle>
          </CardHeader>
          <CardContent>
            {/* Line chart showing cost over time */}
            <div className="h-64 flex items-center justify-center text-muted-foreground">
              Cost trend chart (integrate with recharts)
            </div>
          </CardContent>
        </Card>

        {/* Cost by Service */}
        <Card>
          <CardHeader>
            <CardTitle>Cost Breakdown by Service</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Service</TableHead>
                  <TableHead>Compute</TableHead>
                  <TableHead>Storage</TableHead>
                  <TableHead>Total</TableHead>
                  <TableHead>% of Budget</TableHead>
                  <TableHead>Trend</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[
                  {
                    service: "Spark",
                    compute: 450.20,
                    storage: 25.00,
                    total: 475.20,
                    percent: 23.8,
                    trend: "up",
                  },
                  {
                    service: "PostgreSQL",
                    compute: 180.50,
                    storage: 80.00,
                    total: 260.50,
                    percent: 13.0,
                    trend: "stable",
                  },
                  // ... more services
                ].map((item) => (
                  <TableRow key={item.service}>
                    <TableCell className="font-medium">{item.service}</TableCell>
                    <TableCell>${item.compute.toFixed(2)}</TableCell>
                    <TableCell>${item.storage.toFixed(2)}</TableCell>
                    <TableCell className="font-medium">
                      ${item.total.toFixed(2)}
                    </TableCell>
                    <TableCell>{item.percent}%</TableCell>
                    <TableCell>
                      {item.trend === "up" ? (
                        <TrendingUp className="h-4 w-4 text-red-600" />
                      ) : (
                        <Minus className="h-4 w-4 text-muted-foreground" />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Cost by User */}
        <Card>
          <CardHeader>
            <CardTitle>Top 10 Users by Cost</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Queries</TableHead>
                  <TableHead>Notebooks</TableHead>
                  <TableHead>Workflows</TableHead>
                  <TableHead>Total Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[
                  {
                    user: "john.doe@company.com",
                    queries: 542,
                    notebooks: 23,
                    workflows: 8,
                    cost: 125.43,
                  },
                  // ... more users
                ].map((item) => (
                  <TableRow key={item.user}>
                    <TableCell>{item.user}</TableCell>
                    <TableCell>{item.queries}</TableCell>
                    <TableCell>{item.notebooks}</TableCell>
                    <TableCell>{item.workflows}</TableCell>
                    <TableCell className="font-medium">
                      ${item.cost.toFixed(2)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </AdminLayout>
  )
}
```

---

## 🟡 High: 백업 및 복구

```typescript
// frontend/app/admin/backup/page.tsx
export default function BackupPage() {
  return (
    <AdminLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Backup & Restore</h1>
            <p className="text-muted-foreground">
              Manage system backups and disaster recovery
            </p>
          </div>
          <Button>
            <Play className="mr-2 h-4 w-4" />
            Run Backup Now
          </Button>
        </div>

        {/* Backup Status */}
        <div className="grid grid-cols-3 gap-4">
          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Last Backup</p>
              <p className="text-2xl font-bold">2 hours ago</p>
              <Badge variant="default" className="mt-2">
                Success
              </Badge>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Backup Size</p>
              <p className="text-2xl font-bold">45.2 GB</p>
              <p className="text-xs text-muted-foreground mt-1">
                +2.1 GB from last week
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <p className="text-sm text-muted-foreground">Retention</p>
              <p className="text-2xl font-bold">30 days</p>
              <p className="text-xs text-muted-foreground mt-1">
                42 backups stored
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Backup Schedule */}
        <Card>
          <CardHeader>
            <CardTitle>Backup Schedule</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[
                {
                  name: "PostgreSQL Full Backup",
                  schedule: "Daily at 2:00 AM",
                  retention: "30 days",
                  enabled: true,
                },
                {
                  name: "Iceberg Metadata Backup",
                  schedule: "Every 6 hours",
                  retention: "7 days",
                  enabled: true,
                },
                {
                  name: "Configuration Backup",
                  schedule: "Weekly (Sunday 3:00 AM)",
                  retention: "90 days",
                  enabled: true,
                },
              ].map((backup) => (
                <div
                  key={backup.name}
                  className="flex items-center justify-between p-4 border rounded-lg"
                >
                  <div>
                    <p className="font-medium">{backup.name}</p>
                    <p className="text-sm text-muted-foreground">
                      {backup.schedule} • Retention: {backup.retention}
                    </p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <Switch checked={backup.enabled} />
                    <Button variant="ghost" size="icon">
                      <Settings className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Backup History */}
        <Card>
          <CardHeader>
            <CardTitle>Backup History</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Backup Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[
                  {
                    name: "postgres-backup-20260428-020000",
                    type: "Full",
                    size: "45.2 GB",
                    date: new Date(),
                    status: "success",
                  },
                  // ... more backups
                ].map((backup) => (
                  <TableRow key={backup.name}>
                    <TableCell className="font-mono text-sm">
                      {backup.name}
                    </TableCell>
                    <TableCell>{backup.type}</TableCell>
                    <TableCell>{backup.size}</TableCell>
                    <TableCell>{backup.date.toLocaleString()}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          backup.status === "success" ? "default" : "destructive"
                        }
                      >
                        {backup.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon">
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent>
                          <DropdownMenuItem>
                            <Download className="mr-2 h-4 w-4" />
                            Download
                          </DropdownMenuItem>
                          <DropdownMenuItem>
                            <RefreshCw className="mr-2 h-4 w-4" />
                            Restore
                          </DropdownMenuItem>
                          <DropdownMenuItem className="text-destructive">
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </AdminLayout>
  )
}
```

---

## 📊 구현 우선순위

### Phase 1: 필수 관리 기능 (3-4주)
**목표**: 최소한의 관리 가능

- [ ] 관리자 대시보드 (시스템 개요)
- [ ] 사용자 관리 (목록, 생성, 수정, 삭제)
- [ ] 역할 및 권한 관리
- [ ] 기본 모니터링 (서비스 상태, 리소스)
- [ ] 감사 로그 (읽기 전용)

### Phase 2: 운영 기능 (2-3주)
**목표**: 안정적인 운영

- [ ] 상세 리소스 모니터링
- [ ] 알림 설정 UI
- [ ] 백업 관리
- [ ] 비용 대시보드
- [ ] API 키 관리

### Phase 3: 고급 기능 (3-4주)
**목표**: 효율적인 관리

- [ ] 데이터 거버넌스
- [ ] 비용 최적화 제안
- [ ] 용량 계획
- [ ] 자동화 규칙
- [ ] 팀 관리

---

## 🎯 관리자 페르소나

### Platform Admin (플랫폼 관리자)
**주요 업무**: 시스템 전체 관리

**필요 기능**:
- ⭐⭐⭐⭐⭐ 시스템 모니터링
- ⭐⭐⭐⭐⭐ 사용자 관리
- ⭐⭐⭐⭐⭐ 리소스 관리
- ⭐⭐⭐⭐ 비용 관리
- ⭐⭐⭐⭐ 백업/복구

### Security Admin (보안 관리자)
**주요 업무**: 보안 및 규정 준수

**필요 기능**:
- ⭐⭐⭐⭐⭐ 감사 로그
- ⭐⭐⭐⭐⭐ 권한 관리
- ⭐⭐⭐⭐⭐ 보안 설정
- ⭐⭐⭐⭐ 알림 설정

### Data Admin (데이터 관리자)
**주요 업무**: 데이터 거버넌스

**필요 기능**:
- ⭐⭐⭐⭐⭐ 데이터 카탈로그 관리
- ⭐⭐⭐⭐⭐ 데이터 품질 모니터링
- ⭐⭐⭐⭐ 데이터 계보
- ⭐⭐⭐⭐ 액세스 제어

---

## 📈 예상 효과

### 운영 효율성
| 지표 | 개선 전 | 개선 후 | 개선율 |
|------|---------|---------|--------|
| 사용자 생성 시간 | 30분 (CLI) | 2분 (UI) | **93% ↓** |
| 문제 해결 시간 | 2시간 | 30분 | **75% ↓** |
| 보안 감사 시간 | 4시간 | 30분 | **87% ↓** |
| 비용 분석 시간 | 3시간 | 10분 | **94% ↓** |

### 시스템 안정성
- ✅ **조기 문제 감지**: 실시간 모니터링
- ✅ **빠른 대응**: 알림 및 자동화
- ✅ **데이터 보호**: 자동 백업
- ✅ **비용 통제**: 예산 관리

---

## 🔗 통합 요구사항

### Backend API 추가 필요
```python
# 관리 API 엔드포인트
/api/v1/admin/users              # 사용자 CRUD
/api/v1/admin/roles              # 역할 관리
/api/v1/admin/audit-logs         # 감사 로그
/api/v1/admin/system/stats       # 시스템 통계
/api/v1/admin/system/services    # 서비스 상태
/api/v1/admin/resources          # 리소스 사용량
/api/v1/admin/billing            # 비용 정보
/api/v1/admin/backup             # 백업 관리
/api/v1/admin/alerts             # 알림 설정
```

### Kubernetes 통합
```yaml
# ServiceAccount for admin dashboard
apiVersion: v1
kind: ServiceAccount
metadata:
  name: datapond-admin
  namespace: datapond
---
# ClusterRole for read-only access
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: datapond-admin-reader
rules:
- apiGroups: [""]
  resources: ["pods", "services", "nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets"]
  verbs: ["get", "list", "watch"]
```

---

## 🎓 결론

**관리 UI는 프로덕션 운영의 핵심**입니다. 현재 DataPond는 관리 UI가 전무하여 모든 관리 작업을 kubectl/helm CLI로 수행해야 하는 상태입니다.

### 즉시 구현 필요
1. **사용자 관리** (2주)
2. **시스템 모니터링** (1주)
3. **감사 로그** (1주)

### 기대 효과
- 운영 효율성 **80% 향상**
- 문제 해결 시간 **75% 단축**
- 보안 감사 시간 **87% 단축**

---

**문서 버전**: 1.0  
**다음 리뷰**: 2026-06-28  
**참고 사례**: Databricks Admin Console, Snowflake Account Admin, AWS Console
