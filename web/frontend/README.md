# Veritas Web Frontend

本目录复用 `third_party/elis/system_modules/elis-frontend` 的工程基础设施：

- Vite + React 19
- Tailwind CSS
- ESLint 9 flat config
- Vitest / Testing Library 测试组织
- `src/services/api.js` 集中封装后端 API
- `AppLayout + Sidebar + Topbar + lazy pages` 的工作台结构

视觉和业务交互不复用 ELIS。Veritas 当前采用“审计档案 + 任务控制台”的浅色工作台，服务于论文技术事实复核。

## 开发启动

先启动后端：

```bash
PYTHONPATH=. python3 -m web.backend.veritas_web.app
```

再启动前端：

```bash
cd web/frontend
npm install
npm run dev
```

Vite 默认代理 `/api` 到 `http://127.0.0.1:8765`。

## 构建后单进程演示

```bash
cd web/frontend
npm run build
cd ../..
PYTHONPATH=. python3 -m web.backend.veritas_web.app
```

如果 `web/frontend/dist/index.html` 存在，stdlib backend 会托管构建产物。
