# Veritas 鉴权与多用户支持 PRD

## 文档信息

- 文档状态：已决策 PRD（2026-06-12 决策冻结）
- 目标阶段：接入主产品 + 独立部署
- 目标读者：产品负责人、研发、运维
- 依赖：主产品 JWT 鉴权体系

### 决策记录（2026-06-12）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 架构方案 | Auth Provider 抽象层 | 灵活，支持多种鉴权方式，鉴权逻辑和路由分离 |
| 独立部署用户管理 | SQLite | 比 YAML 灵活，比 Auth0 简单，不依赖外部服务 |
| 前端登录页 | 不实现，用 HTTP Basic Auth | 浏览器原生弹窗，零前端改动，最简单 |
| 现有 case 迁移 | 全部归属 operator | 最安全，不丢失数据 |
| 部署模式 | 双模式（bearer + basic） | bearer 接入主产品，basic 独立部署 |

## Problem Statement

Veritas Web P1 当前无任何鉴权机制，后端绑定 `127.0.0.1:8765`，仅靠 loopback 做访问限制。所有 API 端点完全开放，无用户身份概念。

**需求**：
1. **接入主产品**：公司主产品已有登录注册和 JWT 鉴权，Veritas 作为子模块嵌入
2. **独立部署**：Veritas 也可以单独部署到公网，需要简单的鉴权方案
3. **单租户**：只需要用户级隔离，不需要组织级多租户

**核心约束**：
- 不在 Veritas 内部实现用户注册/登录（重复造轮子）
- 数据必须按用户隔离
- 方案要足够简单，4-5 天内完成

## Solution Options

### 方案 A：Auth Provider 抽象层（推荐）

**架构**：

```text
VeritasRequestHandler
  ↓
AuthMiddleware（鉴权中间件）
  ↓
AuthProvider（抽象接口）
  ├─ NoAuthProvider（本地开发，auth_mode=none）
  ├─ BearerTokenProvider（接入主产品，auth_mode=bearer）
  └─ BasicAuthProvider（独立部署，auth_mode=basic，SQLite + HTTP Basic Auth）
  ↓
CaseStore（数据层，按 user_id 隔离）
```

**两种部署模式**：

| 模式 | auth_mode | 鉴权来源 | 用户管理 | 适用场景 |
|---|---|---|---|---|
| **嵌入主产品** | `bearer` | 主产品签发 JWT | 主产品管理 | 公司内网 |
| **独立部署** | `basic` | HTTP Basic Auth（浏览器原生弹窗） | SQLite | 公网部署 |

**优点**：
- 灵活：支持多种鉴权方式
- 简单：独立部署用 HTTP Basic Auth（浏览器原生弹窗，零前端改动）
- 兼容：本地开发可以用 `none` 模式
- 轻量：SQLite 管理用户，不依赖外部服务

**缺点**：
- 需要实现 3 个 Provider
- HTTP Basic Auth 每次请求都传密码（必须配合 HTTPS）

---

### 方案 B：反向代理鉴权（最简）

**架构**：

```text
客户端
  ↓
Nginx / Caddy（反向代理）
  ├─ 嵌入模式：验证主产品 JWT，传递 X-User-ID header
  └─ 独立模式：Basic Auth 或 Authelia
  ↓
Veritas Web Backend（信任 X-User-ID header）
```

**优点**：
- 后端零改动（只读 X-User-ID header）
- 鉴权逻辑完全在反向代理
- 可以复用现有的 Authelia/Nginx auth 模块

**缺点**：
- 依赖反向代理配置
- 独立部署需要额外配置 Authelia 或 Basic Auth
- 不够灵活（切换鉴权方式需要改 Nginx 配置）

---

### 方案 C：混合方案

**架构**：

```text
Veritas Web Backend
  ├─ 嵌入模式：读取主产品 JWT，验证后提取 user_id
  └─ 独立模式：HTTP Basic Auth + SQLite
```

**核心设计**：
- **嵌入模式**：Veritas 只验证 JWT，不签发
- **独立模式**：HTTP Basic Auth，用户存在 SQLite 中

**优点**：
- 不需要抽象层，直接 if/else
- 零前端改动（浏览器原生 Basic Auth 弹窗）

**缺点**：
- 代码耦合（两种模式混在一起）
- 不够优雅，难以扩展

---

## Recommended: 方案 A（Auth Provider 抽象层）

**理由**：
1. **最灵活**：未来可以无缝接入 OAuth2、SAML 等
2. **最清晰**：鉴权逻辑和路由逻辑分离
3. **最可测**：每个 Provider 可以独立测试
4. **复杂度可控**：3 个 Provider，每个 < 100 行代码
5. **零前端改动**：HTTP Basic Auth 不需要前端登录页

---

## Detailed Design（方案 A）

### 1. 数据模型变更

#### User Identity（新增）

```python
# web/backend/veritas_web/auth.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class AuthContext:
    user_id: str
    email: Optional[str] = None
    roles: list[str] = []  # ["admin", "operator", "viewer"]
    metadata: dict = {}
```

#### CaseRecord 变更

```python
# web/backend/veritas_web/models.py

@dataclass
class CaseRecord:
    case_id: str
    title: str
    status: str
    owner: str  # user_id（已有字段，现在强制绑定）
    created_at: str
    # ... 其他字段
    
    # 新增：访问控制
    visibility: str = "private"  # "private" | "shared" | "public"
    shared_with: list[str] = []  # user_id list（未来扩展）
```

**关键约束**：
- `owner` 必须等于当前登录用户的 `user_id`
- `visibility=private`：只有 owner 可访问
- `visibility=shared`：owner + `shared_with` 列表中的用户可访问
- `visibility=public`：所有登录用户可访问（未来扩展）

---

### 2. Auth Provider 接口

```python
# web/backend/veritas_web/auth.py

from abc import ABC, abstractmethod
from typing import Optional
import jwt

class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, headers: dict) -> Optional[AuthContext]:
        """
        验证请求 headers，返回 AuthContext 或 None（拒绝）。
        
        实现要求：
        - 从 headers 提取 token（Authorization, X-API-Key 等）
        - 验证 token 有效性
        - 提取 user_id, email, roles
        - 返回 AuthContext 或 None
        """
        pass
    
    @abstractmethod
    def is_enabled(self) -> bool:
        """是否启用鉴权（False = 本地开发模式）"""
        pass


class NoAuthProvider(AuthProvider):
    """本地开发模式：无鉴权，默认 operator"""
    
    def authenticate(self, headers):
        return AuthContext(user_id="operator", email="dev@local", roles=["admin"])
    
    def is_enabled(self):
        return False


class BearerTokenProvider(AuthProvider):
    """
    接入主产品模式：验证主产品签发的 JWT
    
    主产品 JWT 结构（Go Gin 后端）：
    - userId: string（MongoDB ObjectID hex）
    - userName: string
    - exp: int64（10天过期）
    - iss: "gin-blog"
    - 签名算法: HS256
    - 无 sub / aud / email / roles
    
    配置：
    - jwt_shared_secret: 与主产品共享的 HS256 密钥
    - jwt_issuer: 固定 "gin-blog"
    """
    
    def __init__(self, shared_secret: str, issuer: str = "gin-blog"):
        self.shared_secret = shared_secret
        self.issuer = issuer
    
    def authenticate(self, headers):
        auth_header = headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header[7:]
        try:
            payload = jwt.decode(
                token,
                self.shared_secret,
                algorithms=["HS256"],
                issuer=self.issuer
                # 注意：主产品 JWT 无 aud 字段，不验证 audience
            )
            # 主产品用 userId 而非标准 sub
            return AuthContext(
                user_id=payload["userId"],
                email=None,  # 主产品 JWT 不传 email
                roles=["operator"],  # 主产品无角色模型，默认 operator
                metadata={
                    "userName": payload.get("userName", ""),
                    "source": "main_product"
                }
            )
        except jwt.InvalidTokenError:
            return None
    
    def is_enabled(self):
        return True


class BasicAuthProvider(AuthProvider):
    """
    独立部署模式：HTTP Basic Auth + SQLite
    
    用户存储在 SQLite 数据库中。
    浏览器自动弹出用户名/密码对话框，零前端改动。
    必须配合 HTTPS 使用（密码明文传输）。
    
    配置：
    - db_path: SQLite 数据库路径
    - secret_key: 密码哈希盐值（可选，使用 bcrypt）
    """
    
    def __init__(self, db_path: str = "veritas_users.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化 SQLite 数据库"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                email TEXT,
                roles TEXT DEFAULT 'operator',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    
    def authenticate(self, headers) -> Optional[AuthContext]:
        """验证 HTTP Basic Auth"""
        auth_header = headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            return None
        
        # 解码 Base64
        import base64
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            return None
        
        # 查询 SQLite
        if not self._verify_password(username, password):
            return None
        
        return AuthContext(
            user_id=username,
            email=self._get_email(username),
            roles=self._get_roles(username)
        )
    
    def _verify_password(self, username: str, password: str) -> bool:
        """验证用户名密码"""
        import sqlite3
        import bcrypt
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return False
        
        password_hash = row[0]
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    
    def add_user(self, username: str, password: str, email: str = None, roles: str = "operator"):
        """添加用户（管理员操作）"""
        import sqlite3
        import bcrypt
        
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO users (username, password_hash, email, roles) VALUES (?, ?, ?, ?)",
            (username, password_hash, email, roles)
        )
        conn.commit()
        conn.close()
    
    def _get_email(self, username: str) -> Optional[str]:
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT email FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    
    def _get_roles(self, username: str) -> list[str]:
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT roles FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        return row[0].split(",") if row and row[0] else ["operator"]
    
    def challenge_headers(self) -> dict:
        """返回 401 时的 WWW-Authenticate header"""
        return {"WWW-Authenticate": 'Basic realm="Veritas"'}
    
    def is_enabled(self):
        return True
```

---

### 3. 配置

```python
# web/backend/veritas_web/config.py

from dataclasses import dataclass, field
from typing import Literal, Optional
import os
import yaml

@dataclass
class AuthConfig:
    mode: Literal["none", "bearer", "basic"] = "none"
    
    # Bearer 模式（接入主产品）
    jwt_shared_secret: str = ""  # HS256 共享密钥（与主产品相同）
    jwt_issuer: str = "gin-blog"  # 主产品固定 issuer
    
    # Basic 模式（独立部署）
    sqlite_db_path: str = "veritas_users.db"
    
    @classmethod
    def from_env(cls) -> "AuthConfig":
        """从环境变量加载配置"""
        mode = os.getenv("VERITAS_AUTH_MODE", "none")
        
        if mode == "bearer":
            return cls(
                mode="bearer",
                jwt_shared_secret=os.getenv("VERITAS_JWT_SECRET", ""),
                jwt_issuer=os.getenv("VERITAS_JWT_ISSUER", "gin-blog")
            )
        elif mode == "basic":
            return cls(
                mode="basic",
                sqlite_db_path=os.getenv("VERITAS_USERS_DB", "veritas_users.db")
            )
        else:
            return cls(mode="none")
```

---

### 4. 中间件集成

```python
# web/backend/veritas_web/app.py

from .auth import AuthProvider, AuthContext, NoAuthProvider
from .config import AuthConfig

class VeritasRequestHandler(BaseHTTPRequestHandler):
    auth_provider: AuthProvider
    auth_context: Optional[AuthContext] = None
    
    def _authenticate(self) -> bool:
        """鉴权检查，返回 True 表示通过"""
        if not self.auth_provider.is_enabled():
            # 本地开发模式
            self.auth_context = AuthContext(user_id="operator", roles=["admin"])
            return True
        
        # 验证 token
        headers = {k: v for k, v in self.headers.items()}
        self.auth_context = self.auth_provider.authenticate(headers)
        
        if not self.auth_context:
            # 401 Unauthorized
            # Basic Auth 模式需要返回 WWW-Authenticate header，浏览器才会弹出登录框
            extra_headers = {}
            if hasattr(self.auth_provider, "challenge_headers"):
                extra_headers = self.auth_provider.challenge_headers()
            self._send_error(401, "Unauthorized", extra_headers=extra_headers)
            return False
        
        return True
    
    def do_GET(self):
        if not self._authenticate():
            return
        self._route_get()
    
    def do_POST(self):
        if not self._authenticate():
            return
        self._route_post()
```

---

### 5. 数据隔离

```python
# web/backend/veritas_web/case_store.py

class CaseStore:
    def list_cases(self, user_id: str) -> list[CaseRecord]:
        """只返回当前用户可访问的 case"""
        all_cases = self._load_all_cases()
        return [
            c for c in all_cases
            if c.owner == user_id
            or c.visibility == "public"
            or (c.visibility == "shared" and user_id in c.shared_with)
        ]
    
    def get_case(self, case_id: str, user_id: str) -> Optional[CaseRecord]:
        """验证 case 归属或访问权限"""
        case = self._load_case(case_id)
        if not case:
            return None
        
        if case.owner == user_id:
            return case
        if case.visibility == "public":
            return case
        if case.visibility == "shared" and user_id in case.shared_with:
            return case
        
        return None  # 无权限
    
    def create_case(self, case: CaseRecord, user_id: str) -> CaseRecord:
        """强制绑定 owner"""
        case.owner = user_id
        self._save_case(case)
        return case
    
    def update_case(self, case_id: str, updates: dict, user_id: str) -> Optional[CaseRecord]:
        """只有 owner 可以更新"""
        case = self.get_case(case_id, user_id)
        if not case or case.owner != user_id:
            return None  # 无权限或不存在
        
        for k, v in updates.items():
            setattr(case, k, v)
        self._save_case(case)
        return case
    
    def delete_case(self, case_id: str, user_id: str) -> bool:
        """只有 owner 可以删除"""
        case = self.get_case(case_id, user_id)
        if not case or case.owner != user_id:
            return False
        
        self._delete_case(case_id)
        return True
```

---

### 6. API 变更

#### 用户管理 CLI（独立部署模式）

```bash
# 添加用户
python -m veritas_web.cli add-user alice --email alice@example.com --roles operator

# 列出用户
python -m veritas_web.cli list-users

# 删除用户
python -m veritas_web.cli delete-user alice

# 修改密码
python -m veritas_web.cli change-password alice
```

#### 现有端点变更

所有涉及 case 的端点都需要传入 `user_id`：

```python
# 之前
GET /api/cases
GET /api/cases/{case_id}
POST /api/cases

# 之后（自动从 auth_context 提取 user_id）
GET /api/cases  # 只返回当前用户的 case
GET /api/cases/{case_id}  # 验证归属
POST /api/cases  # 自动设置 owner = current_user_id
```

**无新增 API 端点**：HTTP Basic Auth 不需要 `/api/auth/login`，浏览器自动处理。

---

### 7. 前端变更

#### 嵌入主产品模式

```javascript
// 主产品前端传递 JWT
<iframe 
  src="https://veritas.internal.company.com"
  // JWT 通过 postMessage 或 URL param 传递
/>

// 或者 SPA 路由
function VeritasPage() {
  const { jwt } = useAuth();  // 从主产品获取 JWT
  
  return (
    <VeritasApp 
      apiBaseUrl="https://veritas.internal.company.com"
      authToken={jwt}
    />
  );
}
```

#### 独立部署模式

**零前端改动**：HTTP Basic Auth 由浏览器自动处理。

- 首次访问时，浏览器弹出用户名/密码对话框
- 用户输入后，浏览器自动在后续请求中附带 `Authorization: Basic ...` header
- 后端返回 401 + `WWW-Authenticate: Basic realm="Veritas"` 时，浏览器重新弹出对话框

前端 API 客户端不需要任何额外代码。

---

### 8. 文件存储隔离

```text
web_data/
├── cases/
│   ├── {user_id_1}/
│   │   ├── {case_id_1}/
│   │   │   ├── case.json
│   │   │   ├── inputs/
│   │   │   └── outputs/
│   │   └── {case_id_2}/
│   └── {user_id_2}/
│       └── {case_id_3}/
```

**迁移脚本**：
- 现有 case 全部归属 `operator` 用户
- 迁移后目录结构：`web_data/cases/operator/{case_id}/`

---

## Implementation Plan

### Phase 0: Auth Provider 抽象层（0.5 天）

**交付物**：
- `web/backend/veritas_web/auth.py`: AuthProvider 接口 + NoAuthProvider
- `web/backend/veritas_web/config.py`: AuthConfig
- 单元测试：test_auth.py

**验证**：
- 本地开发模式（auth_mode=none）正常工作
- 所有现有测试通过

---

### Phase 1: BearerTokenProvider + 数据隔离（1.5 天）

**交付物**：
- `auth.py`: BearerTokenProvider
- `case_store.py`: 按 user_id 隔离
- `app.py`: 中间件集成
- 迁移脚本：现有 case 归属 operator
- 单元测试：test_bearer_auth.py, test_case_isolation.py

**验证**：
- 用主产品 JWT 可以访问 Veritas API
- 用户 A 无法访问用户 B 的 case
- 迁移后现有 case 正常工作

---

### Phase 2: BasicAuthProvider + SQLite + CLI（1 天）

**交付物**：
- `auth.py`: BasicAuthProvider（HTTP Basic Auth + SQLite）
- `cli.py`: 用户管理命令行工具
- 单元测试：test_basic_auth.py

**验证**：
- 独立部署模式：浏览器弹出登录框
- 用户管理 CLI 可以添加/删除用户
- 密码用 bcrypt 哈希存储

---

### Phase 3: 前端集成 + 文档（1 天）

**交付物**：
- 前端 API 客户端：Bearer 模式自动附带 token
- 嵌入主产品 demo
- 独立部署文档（Nginx + HTTPS + Basic Auth）
- 配置示例

**验证**：
- 嵌入主产品可以正常使用
- 独立部署可以正常使用

---

**总时间**：4 天（比原计划少 0.5 天，因为不需要前端登录页）

---

## Success Metrics

- **安全性**：
  - 用户 A 无法访问用户 B 的 case（100% 隔离）
  - 无效 token 被拒绝（401）
  - 过期 token 被拒绝（401）

- **兼容性**：
  - 本地开发模式（auth_mode=none）正常工作
  - 嵌入主产品模式正常工作
  - 独立部署模式正常工作

- **性能**：
  - 鉴权检查 < 10ms
  - 数据隔离不增加查询延迟

---

## Risks

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| 主产品 JWT 格式不兼容 | 中 | 高 | 提前确认 JWT payload 结构 |
| 数据迁移丢失 case | 低 | 高 | 迁移前备份，迁移后验证 |
| 独立部署用户管理复杂 | 中 | 中 | 用配置文件，不接入数据库 |
| 前端登录页体验差 | 低 | 低 | 用最简 UI，够用即可 |

---

## Open Questions（已关闭）

以下问题已在 2026-06-12 决策冻结中关闭：

| 问题 | 决策 | 理由 |
|---|---|---|
| 架构方案选择 | Auth Provider 抽象层（方案 A） | 灵活，鉴权逻辑和路由分离，可测试 |
| 独立部署用户管理 | SQLite | 比 YAML 灵活，比 Auth0 简单，不依赖外部服务 |
| 前端登录页 | 不实现，用 HTTP Basic Auth | 浏览器原生弹窗，零前端改动，最简单 |
| 现有 case 迁移 | 全部归属 operator | 最安全，不丢失数据 |
| 主产品 JWT 结构 | HS256 + userId/userName + iss="gin-blog" | 已确认，无 sub/aud/email/roles |

### 主产品 JWT 适配记录（2026-06-12 确认）

**主产品技术栈**：Go (Gin) + MongoDB + `dgrijalva/jwt-go` v3.2.0

**JWT Payload 结构**：
```json
{
  "userId": "507f1f77bcf86cd799439011",  // MongoDB ObjectID hex
  "userName": "alice",
  "exp": 1717142400,  // 10天过期
  "iss": "gin-blog"
}
```

**适配要点**：
- 签名算法：HS256（对称密钥，非 RS256）
- 用户标识：`userId`（非标准 `sub`）
- 用户名：`userName`（放入 metadata）
- Issuer：固定 `"gin-blog"`
- 无 audience（不验证 aud）
- 无 email（AuthContext.email = None）
- 无 roles（AuthContext.roles = ["operator"]）

**Veritas 配置**：
```bash
VERITAS_AUTH_MODE=bearer
VERITAS_JWT_SECRET=encoding/hexAllYourBase  # 与主产品共享的 HS256 密钥
VERITAS_JWT_ISSUER=gin-blog
```

### 主产品安全风险记录

| 风险 | 严重度 | 说明 | Veritas 应对 |
|---|---|---|---|
| HS256 对称密钥 | 中 | Veritas 必须持有相同密钥，密钥泄露 = 可伪造 token | 环境变量管理，不硬编码；限制服务器访问权限 |
| 密钥硬编码在主产品源码中 | 中 | 任何能接触主产品源码/二进制的人都能获取密钥 | 推动主产品迁移到 RS256 + 环境变量（长期） |
| 旧版 JWT 库（dgrijalva/jwt-go） | 低 | 已停止维护，可能有未修复漏洞 | 主产品侧风险，Veritas 用 PyJWT（维护中）验证即可 |
| 无角色模型 | 低 | 所有主产品用户权限相同 | Veritas 统一分配 "operator" 角色，后续可扩 |
| Token 10 天过期 | 低 | 较长，但无 refresh token | 可接受，主产品用户习惯已建立 |

**已知风险接受**：产品负责人已知悉上述风险，当前阶段接受 HS256 对称密钥方案。长期建议主产品迁移到 RS256 非对称签名。

---

## Further Notes

本 PRD 的核心原则：
1. **不在 Veritas 内部实现用户注册/登录**（重复造轮子）
2. **鉴权逻辑和路由逻辑分离**（Auth Provider 抽象层）
3. **数据隔离必须和身份绑定**（case.owner = user_id）
4. **方案要足够简单**（4 天内完成）
5. **HTTP Basic Auth 是独立部署的关键简化**（零前端改动）
6. **适配主产品 JWT 现状**（HS256 + userId，已知风险接受）

**安全注意事项**：
- HTTP Basic Auth 每次请求都传密码（Base64 编码，非加密），**必须配合 HTTPS**
- 密码必须用 bcrypt 哈希存储，不能明文
- SQLite 数据库文件要有适当的文件权限（chmod 600）
- **主产品 HS256 共享密钥**必须从环境变量读取，不能硬编码
- 共享密钥泄露 = 任何人可伪造 JWT，必须严格控制服务器和部署权限
- 长期建议：推动主产品迁移到 RS256 非对称签名

**主产品技术债务（已知，接受）**：
- HS256 对称密钥（硬编码在源码中）
- `dgrijalva/jwt-go` v3.2.0（已停止维护）
- 无角色模型
- 无 token 撤销机制

**决策冻结日期**：2026-06-12
**下一步**：开始 Phase 0 实施。
