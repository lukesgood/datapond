# DataPond 사용자 경험 개선 가이드

**점검일**: 2026-04-28  
**버전**: 2.1.0  
**대상**: 프로덕션 사용자 중심 기능 개선

---

## 📋 Executive Summary

실제 프로덕션 환경에서 사용자가 DataPond를 효과적으로 활용하기 위한 필수 기능과 UI/UX 개선사항을 분석했습니다.

### 사용자 경험 점수: 58/100

| 카테고리 | 점수 | 상태 |
|---------|------|------|
| 인증/권한 관리 | 0/100 | 🔴 Missing |
| 데이터 카탈로그 | 30/100 | 🔴 Critical |
| 협업 기능 | 20/100 | 🔴 Critical |
| 알림/모니터링 | 25/100 | 🔴 Critical |
| 사용성 | 65/100 | 🟡 Needs Improvement |
| 검색/필터 | 40/100 | 🟡 Needs Improvement |
| 데이터 품질 | 15/100 | 🔴 Critical |
| 비용 관리 | 0/100 | 🔴 Missing |

---

## 🔴 Critical Missing Features (필수 구현)

### 1. 사용자 인증 및 권한 관리

#### 현재 상태
```yaml
# 현재 문제
- 인증 시스템 없음 (누구나 전체 접근 가능)
- 권한 관리 없음 (Role-Based Access Control 부재)
- 사용자 관리 UI 없음
- 감사 로그 없음
```

#### 영향
- **보안**: 민감한 데이터 무단 접근
- **규정 준수**: GDPR, HIPAA 위반
- **책임 추적**: 누가 무엇을 했는지 알 수 없음
- **리소스 관리**: 무제한 리소스 사용

#### 필수 구현 기능

##### 1.1 사용자 인증 시스템
```python
# Backend: api/v1/auth.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# 회원가입
@router.post("/register")
async def register(user: UserCreate, db: Session = Depends(get_db)):
    # 이메일 중복 확인
    if get_user_by_email(db, user.email):
        raise HTTPException(400, "Email already registered")
    
    # 비밀번호 해싱
    hashed_password = pwd_context.hash(user.password)
    
    # 사용자 생성
    db_user = User(
        email=user.email,
        username=user.username,
        hashed_password=hashed_password,
        role="viewer",  # 기본 역할
        created_at=datetime.utcnow()
    )
    db.add(db_user)
    db.commit()
    
    return {"message": "User created successfully"}

# 로그인
@router.post("/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Incorrect username or password")
    
    # JWT 토큰 생성
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "email": user.email,
            "username": user.username,
            "role": user.role
        }
    }

# 현재 사용자 정보
@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
```

##### 1.2 역할 기반 권한 (RBAC)
```python
# models/user.py
from enum import Enum

class UserRole(str, Enum):
    ADMIN = "admin"          # 전체 관리
    DEVELOPER = "developer"  # 데이터 읽기/쓰기, 쿼리 실행
    ANALYST = "analyst"      # 데이터 읽기, 쿼리 실행
    VIEWER = "viewer"        # 데이터 읽기만

class Permission(str, Enum):
    # 데이터
    READ_DATA = "read_data"
    WRITE_DATA = "write_data"
    DELETE_DATA = "delete_data"
    
    # 쿼리
    EXECUTE_QUERY = "execute_query"
    SAVE_QUERY = "save_query"
    
    # 노트북
    CREATE_NOTEBOOK = "create_notebook"
    EDIT_NOTEBOOK = "edit_notebook"
    DELETE_NOTEBOOK = "delete_notebook"
    
    # 워크플로우
    CREATE_WORKFLOW = "create_workflow"
    TRIGGER_WORKFLOW = "trigger_workflow"
    DELETE_WORKFLOW = "delete_workflow"
    
    # 관리
    MANAGE_USERS = "manage_users"
    MANAGE_SETTINGS = "manage_settings"
    VIEW_AUDIT_LOGS = "view_audit_logs"

# 역할별 권한 매핑
ROLE_PERMISSIONS = {
    UserRole.ADMIN: [p for p in Permission],  # 모든 권한
    UserRole.DEVELOPER: [
        Permission.READ_DATA,
        Permission.WRITE_DATA,
        Permission.EXECUTE_QUERY,
        Permission.SAVE_QUERY,
        Permission.CREATE_NOTEBOOK,
        Permission.EDIT_NOTEBOOK,
        Permission.CREATE_WORKFLOW,
        Permission.TRIGGER_WORKFLOW,
    ],
    UserRole.ANALYST: [
        Permission.READ_DATA,
        Permission.EXECUTE_QUERY,
        Permission.SAVE_QUERY,
        Permission.CREATE_NOTEBOOK,
        Permission.EDIT_NOTEBOOK,
    ],
    UserRole.VIEWER: [
        Permission.READ_DATA,
        Permission.EXECUTE_QUERY,
    ],
}

# 권한 체크 데코레이터
def require_permission(permission: Permission):
    def decorator(func):
        async def wrapper(*args, current_user: User = Depends(get_current_user), **kwargs):
            user_permissions = ROLE_PERMISSIONS.get(current_user.role, [])
            if permission not in user_permissions:
                raise HTTPException(403, f"Permission denied: {permission}")
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator

# 사용 예시
@router.post("/queries")
@require_permission(Permission.SAVE_QUERY)
async def save_query(query: QueryCreate, current_user: User = Depends(get_current_user)):
    # 쿼리 저장 로직
    pass
```

##### 1.3 감사 로그
```python
# models/audit_log.py
class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)  # "query_executed", "notebook_created" 등
    resource_type = Column(String)  # "query", "notebook", "workflow"
    resource_id = Column(String)
    details = Column(JSON)  # 추가 정보
    ip_address = Column(String)
    user_agent = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# 감사 로그 미들웨어
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    # 인증된 요청만 로깅
    if "authorization" in request.headers:
        user = get_user_from_token(request.headers["authorization"])
        
        response = await call_next(request)
        
        # POST/PUT/DELETE 요청 로깅
        if request.method in ["POST", "PUT", "DELETE"]:
            log_audit(
                user_id=user.id,
                action=f"{request.method} {request.url.path}",
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )
        
        return response
    
    return await call_next(request)
```

##### 1.4 로그인 UI
```typescript
// frontend/app/login/page.tsx
"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useToast } from "@/components/ui/use-toast"
import { Database } from "lucide-react"

export default function LoginPage() {
  const router = useRouter()
  const { toast } = useToast()
  const [isLoading, setIsLoading] = useState(false)

  const handleLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setIsLoading(true)

    const formData = new FormData(e.currentTarget)
    const username = formData.get("username") as string
    const password = formData.get("password") as string

    try {
      const response = await fetch("/api/v1/auth/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username, password })
      })

      if (!response.ok) throw new Error("Login failed")

      const data = await response.json()
      
      // 토큰 저장
      localStorage.setItem("access_token", data.access_token)
      localStorage.setItem("user", JSON.stringify(data.user))

      toast({ title: "Login successful", description: `Welcome back, ${data.user.username}!` })
      router.push("/")
    } catch (error) {
      toast({ 
        title: "Login failed", 
        description: "Invalid username or password",
        variant: "destructive"
      })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary">
            <Database className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-2xl">DataPond</CardTitle>
          <p className="text-sm text-muted-foreground">Sign in to your account</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username or Email</Label>
              <Input
                id="username"
                name="username"
                type="text"
                placeholder="Enter your username"
                required
                disabled={isLoading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                placeholder="Enter your password"
                required
                disabled={isLoading}
              />
            </div>
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? "Signing in..." : "Sign in"}
            </Button>
          </form>
          <div className="mt-4 text-center text-sm">
            <a href="/forgot-password" className="text-primary hover:underline">
              Forgot password?
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

---

### 2. 데이터 카탈로그 및 메타데이터 관리

#### 현재 상태
```yaml
# 문제점
- 데이터 디스커버리 기능 없음
- 테이블/컬럼 설명 없음
- 데이터 소유자 불명확
- 데이터 계보(Lineage) 추적 불가
- 태그/분류 체계 없음
```

#### 필수 구현 기능

##### 2.1 데이터 카탈로그 UI
```typescript
// frontend/app/catalog/page.tsx
"use client"

import { useState } from "react"
import { DashboardLayout } from "@/components/layout/dashboard-layout"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Search, Database, Table2, Star, Eye, Tag } from "lucide-react"
import { useDataCatalog, useTableDetails } from "@/lib/hooks/use-catalog"

export default function DataCatalogPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const { data: catalog = [], isLoading } = useDataCatalog()
  const { data: tableDetails } = useTableDetails(selectedTable)

  // 검색 필터링
  const filteredCatalog = catalog.filter((item: any) =>
    item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.tags?.some((tag: string) => tag.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold">Data Catalog</h1>
          <p className="text-muted-foreground">
            Discover and explore your data assets
          </p>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tables, columns, or tags..."
            className="pl-10"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Tables List */}
          <div className="col-span-4 space-y-4">
            {filteredCatalog.map((item: any) => (
              <Card
                key={item.id}
                className={`cursor-pointer transition-colors ${
                  selectedTable === item.id ? "border-primary" : "hover:bg-accent"
                }`}
                onClick={() => setSelectedTable(item.id)}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center space-x-2">
                      <Table2 className="h-4 w-4 text-muted-foreground" />
                      <CardTitle className="text-base">{item.name}</CardTitle>
                    </div>
                    {item.is_favorite && <Star className="h-4 w-4 text-yellow-500 fill-yellow-500" />}
                  </div>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="text-sm text-muted-foreground line-clamp-2">
                    {item.description || "No description available"}
                  </p>
                  <div className="flex items-center space-x-2 text-xs text-muted-foreground">
                    <Database className="h-3 w-3" />
                    <span>{item.database}</span>
                    <span>•</span>
                    <span>{item.row_count?.toLocaleString()} rows</span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {item.tags?.slice(0, 3).map((tag: string) => (
                      <Badge key={tag} variant="secondary" className="text-xs">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Table Details */}
          <div className="col-span-8">
            {selectedTable && tableDetails ? (
              <div className="space-y-4">
                {/* Overview */}
                <Card>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div>
                        <CardTitle>{tableDetails.name}</CardTitle>
                        <p className="text-sm text-muted-foreground mt-1">
                          {tableDetails.description}
                        </p>
                      </div>
                      <Button size="sm">
                        <Star className="mr-2 h-4 w-4" />
                        Add to Favorites
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Metadata */}
                    <div className="grid grid-cols-4 gap-4">
                      <div>
                        <p className="text-xs text-muted-foreground">Owner</p>
                        <p className="text-sm font-medium">{tableDetails.owner}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Last Updated</p>
                        <p className="text-sm font-medium">
                          {new Date(tableDetails.updated_at).toLocaleDateString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Row Count</p>
                        <p className="text-sm font-medium">
                          {tableDetails.row_count?.toLocaleString()}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Size</p>
                        <p className="text-sm font-medium">{tableDetails.size}</p>
                      </div>
                    </div>

                    {/* Tags */}
                    <div>
                      <p className="text-sm font-medium mb-2">Tags</p>
                      <div className="flex flex-wrap gap-2">
                        {tableDetails.tags?.map((tag: string) => (
                          <Badge key={tag} variant="outline">
                            <Tag className="mr-1 h-3 w-3" />
                            {tag}
                          </Badge>
                        ))}
                        <Button variant="ghost" size="sm">+ Add Tag</Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Columns */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Schema</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b">
                          <th className="text-left py-2 font-medium">Column</th>
                          <th className="text-left py-2 font-medium">Type</th>
                          <th className="text-left py-2 font-medium">Description</th>
                          <th className="text-left py-2 font-medium">Stats</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tableDetails.columns?.map((col: any) => (
                          <tr key={col.name} className="border-b">
                            <td className="py-2 font-mono">{col.name}</td>
                            <td className="py-2">
                              <Badge variant="secondary">{col.type}</Badge>
                            </td>
                            <td className="py-2 text-muted-foreground">
                              {col.description || "-"}
                            </td>
                            <td className="py-2 text-xs text-muted-foreground">
                              {col.null_percentage ? `${col.null_percentage}% null` : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </CardContent>
                </Card>

                {/* Sample Data */}
                <Card>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">Sample Data</CardTitle>
                      <Button variant="outline" size="sm">
                        <Eye className="mr-2 h-4 w-4" />
                        Query in SQL Lab
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {/* 샘플 데이터 테이블 */}
                  </CardContent>
                </Card>

                {/* Usage Statistics */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Usage Statistics</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <p className="text-2xl font-bold">{tableDetails.query_count || 0}</p>
                        <p className="text-xs text-muted-foreground">Queries (Last 30 days)</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold">{tableDetails.user_count || 0}</p>
                        <p className="text-xs text-muted-foreground">Unique Users</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold">{tableDetails.join_count || 0}</p>
                        <p className="text-xs text-muted-foreground">Common Joins</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            ) : (
              <Card className="flex items-center justify-center h-96">
                <p className="text-muted-foreground">Select a table to view details</p>
              </Card>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  )
}
```

##### 2.2 데이터 계보 (Lineage) 추적
```python
# models/lineage.py
class DataLineage(Base):
    __tablename__ = "data_lineage"
    
    id = Column(Integer, primary_key=True)
    source_type = Column(String)  # "table", "query", "notebook", "workflow"
    source_id = Column(String)
    target_type = Column(String)
    target_id = Column(String)
    transformation = Column(Text)  # SQL 쿼리 또는 변환 로직
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

# 쿼리 실행 시 자동으로 계보 기록
@router.post("/queries/execute")
async def execute_query(
    query: QueryExecute,
    current_user: User = Depends(get_current_user)
):
    result = await run_query(query.sql)
    
    # 계보 추적: 어떤 테이블을 읽고 어떤 결과를 생성했는지
    source_tables = extract_tables_from_sql(query.sql)
    for table in source_tables:
        create_lineage(
            source_type="table",
            source_id=table,
            target_type="query",
            target_id=result.query_id,
            transformation=query.sql,
            created_by=current_user.id
        )
    
    return result
```

---

### 3. 실시간 알림 및 모니터링

#### 필수 기능

##### 3.1 사용자 알림 시스템
```typescript
// frontend/components/notifications/notification-center.tsx
"use client"

import { useState, useEffect } from "react"
import { Bell, Check, AlertCircle, Info, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"

export function NotificationCenter() {
  const [notifications, setNotifications] = useState<any[]>([])
  const [unreadCount, setUnreadCount] = useState(0)

  useEffect(() => {
    // WebSocket 연결로 실시간 알림 수신
    const ws = new WebSocket("ws://backend:8000/ws/notifications")
    
    ws.onmessage = (event) => {
      const notification = JSON.parse(event.data)
      setNotifications((prev) => [notification, ...prev])
      setUnreadCount((count) => count + 1)
      
      // 브라우저 알림
      if (Notification.permission === "granted") {
        new Notification(notification.title, {
          body: notification.message,
          icon: "/logo.png"
        })
      }
    }

    return () => ws.close()
  }, [])

  const markAsRead = (id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    )
    setUnreadCount((count) => Math.max(0, count - 1))
  }

  const markAllAsRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))
    setUnreadCount(0)
  }

  const getIcon = (type: string) => {
    switch (type) {
      case "success":
        return <Check className="h-4 w-4 text-green-600" />
      case "error":
        return <AlertCircle className="h-4 w-4 text-red-600" />
      default:
        return <Info className="h-4 w-4 text-blue-600" />
    }
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <Badge
              className="absolute -top-1 -right-1 h-5 w-5 flex items-center justify-center p-0"
              variant="destructive"
            >
              {unreadCount}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="border-b p-4 flex items-center justify-between">
          <h3 className="font-semibold">Notifications</h3>
          {unreadCount > 0 && (
            <Button variant="ghost" size="sm" onClick={markAllAsRead}>
              Mark all as read
            </Button>
          )}
        </div>
        <ScrollArea className="h-96">
          {notifications.length === 0 ? (
            <div className="p-4 text-center text-sm text-muted-foreground">
              No notifications
            </div>
          ) : (
            notifications.map((notification) => (
              <div
                key={notification.id}
                className={`p-4 border-b hover:bg-accent transition-colors ${
                  !notification.read ? "bg-blue-50 dark:bg-blue-950" : ""
                }`}
              >
                <div className="flex items-start space-x-3">
                  {getIcon(notification.type)}
                  <div className="flex-1 space-y-1">
                    <p className="text-sm font-medium">{notification.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {notification.message}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(notification.created_at).toLocaleString()}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => markAsRead(notification.id)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  )
}
```

##### 3.2 알림 트리거 시나리오
```python
# 알림이 발생해야 하는 상황
NOTIFICATION_SCENARIOS = {
    "query_completed": {
        "title": "Query Completed",
        "message": "Your query '{query_name}' has finished executing",
        "type": "success"
    },
    "query_failed": {
        "title": "Query Failed",
        "message": "Query '{query_name}' failed: {error}",
        "type": "error"
    },
    "workflow_completed": {
        "title": "Workflow Completed",
        "message": "Workflow '{workflow_name}' completed successfully",
        "type": "success"
    },
    "workflow_failed": {
        "title": "Workflow Failed",
        "message": "Workflow '{workflow_name}' failed at task '{task_name}'",
        "type": "error"
    },
    "notebook_shared": {
        "title": "Notebook Shared",
        "message": "{user} shared notebook '{notebook_name}' with you",
        "type": "info"
    },
    "table_updated": {
        "title": "Table Updated",
        "message": "Table '{table_name}' has been updated",
        "type": "info"
    },
    "resource_limit": {
        "title": "Resource Limit Warning",
        "message": "You are approaching your compute resource limit",
        "type": "warning"
    },
    "data_quality_issue": {
        "title": "Data Quality Issue",
        "message": "Data quality check failed for '{table_name}'",
        "type": "error"
    }
}
```

---

### 4. 협업 기능

#### 필수 구현

##### 4.1 노트북/쿼리 공유
```python
# models/shared_resource.py
class SharedResource(Base):
    __tablename__ = "shared_resources"
    
    id = Column(Integer, primary_key=True)
    resource_type = Column(String)  # "notebook", "query", "dashboard"
    resource_id = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))
    shared_with_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    shared_with_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    permission = Column(String)  # "view", "edit", "admin"
    created_at = Column(DateTime, default=datetime.utcnow)

# API
@router.post("/notebooks/{notebook_id}/share")
async def share_notebook(
    notebook_id: str,
    share_request: ShareRequest,
    current_user: User = Depends(get_current_user)
):
    # 소유자 확인
    notebook = get_notebook(notebook_id)
    if notebook.owner_id != current_user.id:
        raise HTTPException(403, "Only owner can share")
    
    # 공유 생성
    share = SharedResource(
        resource_type="notebook",
        resource_id=notebook_id,
        owner_id=current_user.id,
        shared_with_user_id=share_request.user_id,
        permission=share_request.permission
    )
    db.add(share)
    
    # 알림 전송
    send_notification(
        user_id=share_request.user_id,
        type="notebook_shared",
        data={
            "user": current_user.username,
            "notebook_name": notebook.name
        }
    )
    
    return {"message": "Notebook shared successfully"}
```

##### 4.2 댓글 및 협업 노트
```typescript
// 쿼리/노트북에 댓글 달기
interface Comment {
  id: string
  user: User
  content: string
  created_at: Date
  replies: Comment[]
}

function CommentSection({ resourceType, resourceId }: { resourceType: string, resourceId: string }) {
  const [comments, setComments] = useState<Comment[]>([])
  const [newComment, setNewComment] = useState("")

  const addComment = async () => {
    const response = await fetch(`/api/v1/comments`, {
      method: "POST",
      body: JSON.stringify({
        resource_type: resourceType,
        resource_id: resourceId,
        content: newComment
      })
    })
    
    // 댓글 추가 후 리프레시
    fetchComments()
    setNewComment("")
  }

  return (
    <div className="space-y-4">
      <h3 className="font-semibold">Comments ({comments.length})</h3>
      
      {/* 댓글 입력 */}
      <div className="flex space-x-2">
        <Input
          placeholder="Add a comment..."
          value={newComment}
          onChange={(e) => setNewComment(e.target.value)}
        />
        <Button onClick={addComment}>Post</Button>
      </div>

      {/* 댓글 목록 */}
      <div className="space-y-3">
        {comments.map((comment) => (
          <div key={comment.id} className="border-l-2 pl-4">
            <div className="flex items-center space-x-2 mb-1">
              <span className="font-medium text-sm">{comment.user.username}</span>
              <span className="text-xs text-muted-foreground">
                {new Date(comment.created_at).toLocaleString()}
              </span>
            </div>
            <p className="text-sm">{comment.content}</p>
            
            {/* 답글 */}
            {comment.replies?.map((reply) => (
              <div key={reply.id} className="ml-4 mt-2 border-l-2 pl-4">
                {/* 답글 렌더링 */}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
```

---

### 5. 데이터 품질 모니터링

#### 필수 기능

##### 5.1 데이터 품질 체크
```python
# models/data_quality.py
class DataQualityRule(Base):
    __tablename__ = "data_quality_rules"
    
    id = Column(Integer, primary_key=True)
    name = Column(String)
    table_name = Column(String)
    rule_type = Column(String)  # "not_null", "unique", "range", "pattern"
    column_name = Column(String)
    condition = Column(JSON)
    severity = Column(String)  # "critical", "warning", "info"
    enabled = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"))

class DataQualityCheck(Base):
    __tablename__ = "data_quality_checks"
    
    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("data_quality_rules.id"))
    status = Column(String)  # "passed", "failed", "warning"
    row_count = Column(Integer)
    failed_count = Column(Integer)
    details = Column(JSON)
    checked_at = Column(DateTime, default=datetime.utcnow)

# 데이터 품질 체크 실행
@router.post("/data-quality/check/{table_name}")
async def check_data_quality(table_name: str):
    rules = get_active_rules(table_name)
    results = []
    
    for rule in rules:
        if rule.rule_type == "not_null":
            # NULL 체크
            null_count = db.execute(f"""
                SELECT COUNT(*) FROM {table_name}
                WHERE {rule.column_name} IS NULL
            """).scalar()
            
            status = "passed" if null_count == 0 else "failed"
            results.append({
                "rule": rule.name,
                "status": status,
                "failed_count": null_count
            })
            
        elif rule.rule_type == "unique":
            # 중복 체크
            duplicate_count = db.execute(f"""
                SELECT COUNT(*) - COUNT(DISTINCT {rule.column_name})
                FROM {table_name}
            """).scalar()
            
            status = "passed" if duplicate_count == 0 else "failed"
            results.append({
                "rule": rule.name,
                "status": status,
                "failed_count": duplicate_count
            })
    
    # 실패한 규칙이 있으면 알림
    if any(r["status"] == "failed" for r in results):
        send_notification(
            type="data_quality_issue",
            data={"table_name": table_name}
        )
    
    return results
```

##### 5.2 데이터 프로파일링
```python
# 테이블 통계 자동 수집
@router.post("/tables/{table_name}/profile")
async def profile_table(table_name: str):
    profile = {
        "table_name": table_name,
        "row_count": get_row_count(table_name),
        "columns": []
    }
    
    columns = get_table_columns(table_name)
    
    for column in columns:
        col_stats = {
            "name": column.name,
            "type": column.type,
            "null_count": get_null_count(table_name, column.name),
            "null_percentage": get_null_percentage(table_name, column.name),
            "distinct_count": get_distinct_count(table_name, column.name),
            "min": get_min(table_name, column.name) if is_numeric(column.type) else None,
            "max": get_max(table_name, column.name) if is_numeric(column.type) else None,
            "avg": get_avg(table_name, column.name) if is_numeric(column.type) else None,
        }
        profile["columns"].append(col_stats)
    
    # 프로파일 저장
    save_table_profile(profile)
    
    return profile
```

---

### 6. 검색 및 필터 개선

#### 현재 문제
- 전역 검색 없음
- 고급 필터 부족
- 최근 검색 히스토리 없음

#### 개선 방안

##### 6.1 전역 검색 (Command Palette)
```typescript
// frontend/components/search/command-palette.tsx
"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Search, Table2, FileCode, Workflow, Database } from "lucide-react"

export function CommandPalette() {
  const router = useRouter()
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((open) => !open)
      }
    }
    document.addEventListener("keydown", down)
    return () => document.removeEventListener("keydown", down)
  }, [])

  const searchResults = [
    {
      group: "Tables",
      items: [
        { icon: Table2, title: "users", subtitle: "PostgreSQL • 1.2M rows", action: () => router.push("/catalog/users") },
        { icon: Table2, title: "orders", subtitle: "PostgreSQL • 850K rows", action: () => router.push("/catalog/orders") },
      ]
    },
    {
      group: "Notebooks",
      items: [
        { icon: FileCode, title: "Customer Analysis", subtitle: "Modified 2 days ago", action: () => router.push("/notebooks/123") },
      ]
    },
    {
      group: "Workflows",
      items: [
        { icon: Workflow, title: "Daily ETL", subtitle: "Last run: 2 hours ago", action: () => router.push("/workflows/daily-etl") },
      ]
    },
  ]

  return (
    <>
      <Button
        variant="outline"
        className="relative w-full justify-start text-sm text-muted-foreground sm:pr-12 md:w-40 lg:w-64"
        onClick={() => setOpen(true)}
      >
        <Search className="mr-2 h-4 w-4" />
        <span className="hidden lg:inline-flex">Search...</span>
        <span className="inline-flex lg:hidden">Search...</span>
        <kbd className="pointer-events-none absolute right-1.5 top-2 hidden h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100 sm:flex">
          <span className="text-xs">⌘</span>K
        </kbd>
      </Button>
      
      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Type to search..." />
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>
          {searchResults.map((group) => (
            <CommandGroup key={group.group} heading={group.group}>
              {group.items.map((item, i) => (
                <CommandItem
                  key={i}
                  onSelect={() => {
                    item.action()
                    setOpen(false)
                  }}
                >
                  <item.icon className="mr-2 h-4 w-4" />
                  <div className="flex flex-col">
                    <span>{item.title}</span>
                    <span className="text-xs text-muted-foreground">{item.subtitle}</span>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
      </CommandDialog>
    </>
  )
}
```

---

### 7. 비용 관리 및 리소스 추적

#### 필수 기능

##### 7.1 쿼리 비용 예측
```python
# 쿼리 실행 전 비용 예측
@router.post("/queries/estimate-cost")
async def estimate_query_cost(query: str):
    # 쿼리 플랜 분석
    explain_result = db.execute(f"EXPLAIN {query}")
    
    # 스캔할 데이터 크기 계산
    estimated_rows = extract_rows_from_plan(explain_result)
    data_size_bytes = estimated_rows * AVG_ROW_SIZE
    
    # 비용 계산 (예: Trino의 경우 스캔 데이터 기준)
    cost_per_tb = 5.00  # $5 per TB scanned
    estimated_cost = (data_size_bytes / 1e12) * cost_per_tb
    
    return {
        "estimated_rows": estimated_rows,
        "data_size_gb": data_size_bytes / 1e9,
        "estimated_cost_usd": round(estimated_cost, 4),
        "estimated_time_seconds": estimate_execution_time(explain_result)
    }
```

##### 7.2 사용자별 리소스 사용량 대시보드
```typescript
// frontend/app/usage/page.tsx
function UsageDashboard() {
  const { data: usage } = useResourceUsage()

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Resource Usage</h1>

      {/* 현재 월 사용량 */}
      <div className="grid grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-2xl font-bold">{usage.query_count}</div>
            <p className="text-xs text-muted-foreground">Queries Executed</p>
            <Progress value={usage.query_count / usage.query_limit * 100} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-1">
              {usage.query_count} / {usage.query_limit} (monthly limit)
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-2xl font-bold">${usage.cost.toFixed(2)}</div>
            <p className="text-xs text-muted-foreground">Compute Cost (MTD)</p>
            <Progress value={usage.cost / usage.budget * 100} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-1">
              ${usage.cost.toFixed(2)} / ${usage.budget.toFixed(2)} budget
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-2xl font-bold">{usage.data_scanned_tb.toFixed(2)} TB</div>
            <p className="text-xs text-muted-foreground">Data Scanned</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-2xl font-bold">{usage.storage_gb.toFixed(1)} GB</div>
            <p className="text-xs text-muted-foreground">Storage Used</p>
          </CardContent>
        </Card>
      </div>

      {/* 사용량 추이 차트 */}
      <Card>
        <CardHeader>
          <CardTitle>Cost Trend (Last 30 Days)</CardTitle>
        </CardHeader>
        <CardContent>
          {/* 시간별 비용 차트 */}
        </CardContent>
      </Card>

      {/* 가장 비싼 쿼리 TOP 10 */}
      <Card>
        <CardHeader>
          <CardTitle>Most Expensive Queries</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left py-2">Query</th>
                <th className="text-left py-2">Data Scanned</th>
                <th className="text-left py-2">Cost</th>
                <th className="text-left py-2">Date</th>
              </tr>
            </thead>
            <tbody>
              {usage.top_queries?.map((q: any) => (
                <tr key={q.id} className="border-b">
                  <td className="py-2 font-mono text-xs">{q.query.substring(0, 50)}...</td>
                  <td className="py-2">{q.data_scanned_gb.toFixed(2)} GB</td>
                  <td className="py-2">${q.cost.toFixed(4)}</td>
                  <td className="py-2">{new Date(q.executed_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
```

---

## 📊 UI/UX 개선 우선순위

### Phase 1: 필수 (1-2개월)
**목표**: 프로덕션 사용 가능 최소 기능

- [ ] 사용자 인증/권한 시스템
- [ ] 데이터 카탈로그 기본 기능
- [ ] 실시간 알림 시스템
- [ ] 전역 검색 (Command Palette)

### Phase 2: 협업 (1개월)
**목표**: 팀 협업 지원

- [ ] 노트북/쿼리 공유
- [ ] 댓글 시스템
- [ ] 팀 관리 기능

### Phase 3: 운영 (1개월)
**목표**: 안정적인 운영

- [ ] 데이터 품질 모니터링
- [ ] 감사 로그 UI
- [ ] 비용 관리 대시보드

### Phase 4: 고급 (지속적)
**목표**: 생산성 향상

- [ ] 데이터 계보 시각화
- [ ] AI 쿼리 추천
- [ ] 자동 문서화

---

## 🎨 UI/UX 모범 사례

### 1. 응답성 피드백
```typescript
// 모든 액션에 즉각적인 피드백
const handleAction = async () => {
  // 1. 낙관적 UI 업데이트
  setData(optimisticData)
  
  // 2. 로딩 상태 표시
  setLoading(true)
  
  try {
    // 3. API 호출
    const result = await api.execute()
    
    // 4. 성공 토스트
    toast({ title: "Success", description: "Action completed" })
    
    // 5. 데이터 갱신
    setData(result)
  } catch (error) {
    // 6. 에러 처리
    toast({ title: "Error", description: error.message, variant: "destructive" })
    
    // 7. 롤백
    setData(previousData)
  } finally {
    setLoading(false)
  }
}
```

### 2. 키보드 단축키
```typescript
// 주요 액션에 단축키 지원
const SHORTCUTS = {
  "cmd+k": "Open command palette",
  "cmd+s": "Save current work",
  "cmd+enter": "Run query/cell",
  "cmd+/": "Toggle comment",
  "cmd+shift+f": "Format code",
  "esc": "Close modal/cancel",
}
```

### 3. 상태 표시
```typescript
// 명확한 상태 전달
<Badge variant={getStatusVariant(status)}>
  {status === "running" && <RefreshCw className="mr-1 h-3 w-3 animate-spin" />}
  {status === "success" && <Check className="mr-1 h-3 w-3" />}
  {status === "failed" && <X className="mr-1 h-3 w-3" />}
  {status}
</Badge>
```

### 4. 빈 상태 처리
```typescript
// 의미 있는 빈 상태 표시
<EmptyState
  icon={<Database className="h-12 w-12" />}
  title="No queries yet"
  description="Create your first query to get started"
  action={
    <Button onClick={() => router.push('/sql')}>
      Create Query
    </Button>
  }
/>
```

---

## 📈 성공 지표 (KPI)

### 사용자 참여도
- **일일 활성 사용자 (DAU)**: 목표 80% 이상
- **주간 활성 사용자 (WAU)**: 목표 95% 이상
- **평균 세션 시간**: 목표 30분 이상

### 생산성
- **쿼리 실행 성공률**: 목표 95% 이상
- **평균 쿼리 응답 시간**: 목표 < 5초
- **노트북 공유율**: 목표 40% 이상

### 만족도
- **NPS (Net Promoter Score)**: 목표 > 50
- **사용자 만족도**: 목표 4.5/5 이상
- **기능 요청 해결률**: 목표 80% 이상

---

## 🎯 결론

현재 DataPond는 **기술적으로는 우수하지만 사용자 경험 측면에서는 개선이 필요**합니다.

### 즉시 구현 필요 (Critical)
1. 사용자 인증/권한 시스템 (보안 필수)
2. 데이터 카탈로그 (디스커버리 필수)
3. 실시간 알림 (사용자 경험 필수)

### 중기 구현 (3-6개월)
1. 협업 기능 (공유, 댓글)
2. 데이터 품질 모니터링
3. 비용 관리

### 장기 개선 (6개월+)
1. AI 기반 추천
2. 고급 데이터 계보
3. 자동 문서화

**개선 후 예상 점수**: 58 → **85/100**

---

**문서 버전**: 1.0  
**다음 리뷰**: 2026-06-28  
**피드백**: [GitHub Issues](https://github.com/lukesgood/datapond/issues)
