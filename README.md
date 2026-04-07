# Cape Agent

An open-source desktop AI agent that can browse the web, write code, and generate documents — all from a single chat interface.

Built with **Electron + React** on the frontend and **FastAPI + [CAMEL-AI](https://github.com/camel-ai/camel)** on the backend. Cape Agent uses a multi-agent workforce architecture: a coordinator decomposes complex tasks and routes subtasks to specialized agents (browser, developer, document), then synthesizes the results.

## Features

- **Multi-Agent Workforce** — Complex tasks are automatically decomposed and dispatched to specialized agents (browser, developer, document), coordinated by a central planner.
- **Browser Automation** — Built-in Chromium browser panel with CDP (Chrome DevTools Protocol) integration. The agent can navigate, click, fill forms, extract content, and more.
- **Code Execution** — Developer agent can write and run code in a sandboxed environment.
- **Document Generation** — Create documents, summaries, and reports from research or conversation context.
- **Multi-Provider Support** — Works with OpenAI, Anthropic, Google Gemini, DeepSeek, Groq, Mistral, Ollama (local), and MiniMax.
- **Streaming Responses** — Real-time SSE streaming with agent step tracking so you can see what each agent is doing.
- **Conversation History** — Persistent chat history stored in a local SQLite database.
- **Dark / Light Theme** — System-aware theme toggle.

## Prerequisites

| Dependency | Version |
|---|---|
| **Python** | >= 3.10 |
| **Node.js** | >= 18 |
| **npm** | >= 9 |
| **uv** (recommended) | latest |

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/cape2333/cape-agent.git
cd cape-agent
```

### 2. Install backend dependencies

Using `uv` (recommended — much faster):

```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install -e .
```

Or with plain `pip`:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> The backend uses [CAMEL-AI](https://github.com/camel-ai/camel) which has many optional deps. If you only need certain providers you can install a lighter subset, but `pip install -e .` will get everything working.
>
> **Tip:** If you skip this step, `npm run dev` will auto-create the `.venv` and install dependencies on first run via `scripts/dev.sh`.

### 3. Install frontend dependencies

```bash
cd frontend
npm install
```

### 4. Run

From the project root:

```bash
npm run dev
```

This starts both the FastAPI backend and the Electron app. The script will:
1. Launch the backend on an available port (defaults to 8001)
2. Wait for the backend health check to pass
3. Launch the Electron frontend

You can also run them separately:

```bash
# Backend only (with hot reload)
npm run dev:backend

# Frontend only (assumes backend is already running)
npm run dev:frontend
```

### 5. Configure your API key

Once the app opens, click the **Settings** icon and configure your preferred provider:

| Provider | Requires API Key | Supports Custom Base URL |
|---|---|---|
| OpenAI | Yes (`OPENAI_API_KEY`) | Yes |
| Anthropic | Yes (`ANTHROPIC_API_KEY`) | Yes |
| Google Gemini | Yes (`GOOGLE_API_KEY`) | Yes |
| DeepSeek | Yes (`DEEPSEEK_API_KEY`) | Yes |
| Groq | Yes (`GROQ_API_KEY`) | No |
| Mistral | Yes (`MISTRAL_API_KEY`) | Yes |
| Ollama | No (local) | Yes (required) |
| MiniMax | No | Yes (required) |

You can enter API keys directly in the Settings modal — they are stored locally in SQLite, never sent anywhere except to the provider's API.

## Project Structure

```
cape-agent/
├── backend/                  # Python FastAPI backend
│   ├── main.py               # Entry point, dynamic port allocation
│   ├── pyproject.toml        # Python dependencies
│   └── app/
│       ├── api/              # REST + SSE endpoints
│       │   ├── chat.py       # Streaming chat (SSE)
│       │   ├── conversations.py
│       │   ├── browser.py    # Browser control via CDP
│       │   └── settings.py
│       ├── agents/           # Multi-agent workforce
│       │   ├── workforce.py  # Coordinator + task decomposition
│       │   └── factory.py    # Agent factory (browser, developer, document)
│       ├── services/         # Business logic
│       │   ├── agent_service.py
│       │   ├── browser_service.py
│       │   └── conversation_service.py
│       └── models/           # DB + Pydantic schemas
├── frontend/                 # Electron + React + Vite
│   ├── src/
│   │   ├── main/             # Electron main process
│   │   │   ├── index.ts      # Window + BrowserPanelManager
│   │   │   └── preload.ts    # IPC bridge
│   │   └── renderer/         # React app
│   │       ├── components/   # UI components
│   │       ├── stores/       # Zustand state
│   │       ├── services/     # API client (HTTP + SSE)
│   │       └── hooks/        # React hooks
│   └── package.json
├── scripts/
│   └── dev.sh                # Dev orchestration script
└── package.json              # Root scripts (npm run dev)
```

## Tech Stack

- **Frontend**: Electron 33, React 18, TypeScript, Vite, Tailwind CSS, Zustand
- **Backend**: FastAPI, Uvicorn, CAMEL-AI, SQLite (aiosqlite)
- **Communication**: REST API + Server-Sent Events (SSE)
- **Browser Automation**: Chrome DevTools Protocol (CDP)
- **Build**: Electron Forge

## Packaging

To build distributable packages:

```bash
cd frontend
npm run make
```

This uses Electron Forge to create platform-specific installers (`.dmg` / `.exe` / `.deb` / `.rpm`).

## License

[MIT](LICENSE)
