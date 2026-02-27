# cape-agent
a agent that can do anything in your computer 


  Backend (Python FastAPI)                                                                                                                                                                        
  - main.py — FastAPI app with lifespan, CORS, health endpoint
  - app/models/database.py — SQLite init with conversations, messages, settings tables                                                                                                            
  - app/models/schemas.py — Pydantic models for all request/response types                                                                                                                        
  - app/api/conversations.py — CRUD endpoints for conversations + messages                                                                                                                        
  - app/api/settings.py — GET/PUT settings with JSON storage in SQLite                                                                                                                            
  - app/api/chat.py — POST SSE streaming endpoint                                                                                                                                                 
  - app/services/conversation_service.py — Conversation/message business logic
  - app/services/agent_service.py — CAMEL ChatAgent integration with streaming, multi-provider support

  Frontend (Electron + React + Tailwind + Zustand)
  - src/main/index.ts — Electron window creation, Python lifecycle management
  - src/main/python-manager.ts — Spawn/health-check/stop Python backend
  - src/main/preload.ts — contextBridge for backend URL
  - src/renderer/stores/store.ts — Zustand store (conversations, messages, streaming, settings)
  - src/renderer/services/api.ts — HTTP + SSE client for all API endpoints
  - src/renderer/hooks/ — useConversations, useChat, useSettings
  - src/renderer/components/layout/ — Sidebar, ChatArea, InputBar
  - src/renderer/components/chat/ — MessageBubble, StreamingMessage
  - src/renderer/components/settings/ — SettingsModal, ProviderForm

  To run:
  1. Backend: cd backend && python main.py
  2. Frontend: cd frontend && npm start
  3. Or both: npm run dev (from root)
