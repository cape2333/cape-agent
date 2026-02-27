                                                                                                                                                                                                                               
 Here is Claude's plan:                                                                                                                                                                                                         
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Cape Agent MVP - Implementation Plan                   
                                                                                                                                                                                                                                
 Context                                                                                                                                                                                                                        
                                                                                                                                                                                                                                
 构建一个类似 Manus 的跨端 AI Agent 桌面客户端。第一个版本是一个简单的聊天客户端，支持多模型配置、对话管理和流式输出。                                                                                                          
                                                                                                                                                                                                                                
 Tech Stack
 ┌────────────┬─────────────────────────────────────┐                                                                                                                                                                           
 │     层     │                选型                 │                                                                                                                                                                           
 ├────────────┼─────────────────────────────────────┤
 │ 桌面框架   │ Electron                            │
 ├────────────┼─────────────────────────────────────┤
 │ 前端       │ React + TypeScript + Tailwind CSS   │
 ├────────────┼─────────────────────────────────────┤
 │ 状态管理   │ Zustand                             │
 ├────────────┼─────────────────────────────────────┤
 │ 后端       │ Python + FastAPI                    │
 ├────────────┼─────────────────────────────────────┤
 │ Agent 框架 │ CAMEL-AI (ModelFactory + ChatAgent) │
 ├────────────┼─────────────────────────────────────┤
 │ 数据库     │ SQLite (aiosqlite)                  │
 ├────────────┼─────────────────────────────────────┤
 │ 前后端通信 │ HTTP REST + SSE (流式)              │
 └────────────┴─────────────────────────────────────┘
 Project Structure

 cape-agent/
 ├── package.json                         # 根: orchestrate 脚本
 ├── frontend/                            # Electron + React
 │   ├── package.json
 │   ├── vite.config.ts
 │   ├── tailwind.config.js
 │   ├── index.html
 │   ├── forge.config.ts
 │   └── src/
 │       ├── main/                        # Electron 主进程
 │       │   ├── index.ts                 # 窗口创建, Python 生命周期
 │       │   ├── python-manager.ts        # 启动/停止/健康检查 Python 后端
 │       │   └── preload.ts               # contextBridge IPC
 │       └── renderer/                    # React 应用
 │           ├── index.tsx
 │           ├── index.css
 │           ├── App.tsx                  # 根布局: 侧边栏 + 聊天区
 │           ├── components/
 │           │   ├── layout/
 │           │   │   ├── Sidebar.tsx       # 对话列表
 │           │   │   ├── ChatArea.tsx      # 消息展示
 │           │   │   └── InputBar.tsx      # 输入框 + 发送按钮
 │           │   ├── chat/
 │           │   │   ├── MessageBubble.tsx # 单条消息
 │           │   │   └── StreamingMessage.tsx # 流式渲染中的消息
 │           │   └── settings/
 │           │       ├── SettingsModal.tsx # 设置弹窗
 │           │       └── ProviderForm.tsx  # 厂商/模型/Key 配置表单
 │           ├── hooks/
 │           │   ├── useChat.ts
 │           │   ├── useConversations.ts
 │           │   └── useSettings.ts
 │           ├── services/
 │           │   └── api.ts               # HTTP + SSE 客户端
 │           ├── stores/
 │           │   └── store.ts             # Zustand 全局状态
 │           └── types/
 │               └── index.ts
 ├── backend/                             # Python FastAPI
 │   ├── pyproject.toml
 │   ├── main.py                          # FastAPI 入口 + uvicorn
 │   └── app/
 │       ├── api/
 │       │   ├── chat.py                  # POST /api/chat (SSE 流式)
 │       │   ├── conversations.py         # 对话 CRUD
 │       │   └── settings.py              # 设置读写
 │       ├── models/
 │       │   ├── schemas.py               # Pydantic 数据模型
 │       │   └── database.py              # SQLite 初始化 + 连接
 │       └── services/
 │           ├── agent_service.py         # CAMEL ChatAgent 封装
 │           └── conversation_service.py  # 对话业务逻辑
 └── scripts/
     └── dev.sh

 API Design
 ┌────────┬─────────────────────────────────┬────────────────┐
 │ Method │              Path               │  Description   │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ GET    │ /health                         │ 健康检查       │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ POST   │ /api/chat                       │ 流式聊天 (SSE) │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ GET    │ /api/conversations              │ 对话列表       │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ POST   │ /api/conversations              │ 创建对话       │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ DELETE │ /api/conversations/:id          │ 删除对话       │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ GET    │ /api/conversations/:id/messages │ 获取消息       │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ GET    │ /api/settings                   │ 读取设置       │
 ├────────┼─────────────────────────────────┼────────────────┤
 │ PUT    │ /api/settings                   │ 更新设置       │
 └────────┴─────────────────────────────────┴────────────────┘
 流式输出 SSE 格式

 data: {"type": "delta", "content": "Hello"}
 data: {"type": "delta", "content": " there"}
 data: {"type": "done", "content": "Hello there"}

 Streaming End-to-End Flow

 用户输入 → InputBar → useChat.sendMessage()
   → Zustand Store (添加 user message, isStreaming=true)
   → api.ts fetch POST /api/chat (ReadableStream)
   → FastAPI endpoint → CAMEL ChatAgent.step() (stream=True)
   → LLM Provider API (token-by-token)
   → FastAPI yield SSE events
   → api.ts 解析 SSE → store.appendStreamChunk()
   → StreamingMessage 实时渲染
   → 完成后 store.finalizeStream() → 保存到 messages[]

 Implementation Phases (7 phases)

 Phase 1: Project Scaffolding

 - npx create-electron-app frontend --template=vite-typescript
 - 添加 React + Tailwind CSS 到 frontend
 - 创建 backend Python 项目, FastAPI + /health endpoint
 - 验证: Electron 窗口打开, curl /health 返回 OK

 Phase 2: Backend Data Layer + REST API

 - 实现 SQLite 数据库初始化 (database.py)
 - 实现 Pydantic schemas (schemas.py)
 - 实现对话 CRUD service + routes (conversation_service.py, conversations.py)
 - 实现设置 API (settings.py)
 - 验证: curl 测试所有 CRUD 接口

 Phase 3: Backend CAMEL Integration + Streaming

 - 实现 agent_service.py — ModelFactory 创建模型, ChatAgent 流式输出
 - 实现 /api/chat SSE endpoint (chat.py)
 - 验证: curl 测试流式 SSE 输出

 Phase 4: Electron Python Process Management

 - 实现 python-manager.ts — spawn/health-check/stop
 - 更新 index.ts — app.ready 启动, app.will-quit 停止
 - 实现 preload.ts — expose getBackendUrl()
 - 验证: Electron 启动时自动拉起 Python, 退出时自动关闭

 Phase 5: React UI — Layout + Conversation Management

 - 实现 Zustand store
 - 实现 api.ts (非流式接口)
 - 构建 App.tsx 布局 (Sidebar + ChatArea + InputBar)
 - 实现 Sidebar, ChatArea, MessageBubble, InputBar 组件
 - 实现 useConversations hook
 - 验证: 可创建/切换/删除对话, UI 正常显示

 Phase 6: React UI — Streaming Chat

 - 实现 api.ts 的 SSE 流式函数
 - 实现 StreamingMessage 组件
 - 实现 useChat hook
 - 串联: InputBar → useChat → api.ts → store → StreamingMessage
 - 验证: 发送消息后实时逐字显示 AI 回复

 Phase 7: Settings UI

 - 实现 SettingsModal + ProviderForm
 - 实现 useSettings hook
 - 连接设置到聊天请求
 - 验证: 配置不同厂商 API Key 后可正常对话

 Key Dependencies

 Frontend: electron, react, react-dom, zustand, react-markdown, tailwindcss, lucide-react, get-port

 Backend: fastapi, uvicorn, camel-ai[all], aiosqlite, pydantic

 Verification

 1. 启动应用 → Electron 窗口打开, Python 后端自动启动
 2. 打开设置 → 配置 OpenAI API Key
 3. 点击新建对话 → 左侧出现新对话
 4. 输入消息发送 → 右侧实时流式显示 AI 回复
 5. 切换不同对话 → 消息历史正确加载
 6. 切换模型厂商 → 使用不同模型对话
 7. 关闭应用 → Python 进程正常退出