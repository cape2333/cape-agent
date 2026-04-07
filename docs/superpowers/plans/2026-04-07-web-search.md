# Browser Agent Web Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Browser Agent a real `search_google` (or `search_duckduckgo`) tool, replacing the current "drive the browser to bing.com" workflow with a search-first / browser-second pattern.

**Architecture:** Add a thin `SearchToolkit` wrapper in `backend/app/toolkits/` that composes CAMEL-AI's built-in `SearchToolkit` and exposes a `get_can_use_tools()` classmethod. The classmethod returns exactly one search tool: `search_google` if `GOOGLE_API_KEY` + `SEARCH_ENGINE_ID` are both set, otherwise `search_duckduckgo` (zero-config). Wire this into `create_browser_agent()` and rewrite the relevant prompt sections.

**Tech Stack:** Python 3.10, FastAPI, CAMEL-AI 0.2.90a6, pytest. The `ddgs` PyPI package (which CAMEL's DuckDuckGo backend depends on) is already installed via the `camel-ai[all]` extra.

**Spec:** `docs/superpowers/specs/2026-04-07-web-search-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/toolkits/search_toolkit.py` | Create | `SearchToolkit` class with `get_can_use_tools()` classmethod |
| `backend/tests/test_search_toolkit.py` | Create | Unit tests for the three branches of `get_can_use_tools()` |
| `backend/app/agents/factory/browser.py` | Modify | Append search tools to the tool list; rewrite `<web_search_workflow>`, `<mandatory_instructions>`, and `<capabilities>` |
| `backend/.env.example` | Create | Document `GOOGLE_API_KEY` and `SEARCH_ENGINE_ID` (optional, with link to Custom Search docs) |

**Out of scope (do NOT touch):**
- `backend/app/models/schemas.py` (no `AppSettings` extension this round)
- Any frontend file
- `developer.py`, `document.py`, `classifier.py` factories
- `backend/app/services/agent_service.py` (the call site of `create_browser_agent` is unchanged because the factory's signature stays the same)

---

## Pre-flight context (read this first)

**Verified facts about the installed CAMEL-AI 0.2.90a6:**

- `camel.toolkits.SearchToolkit.__init__(self, timeout=None, exclude_domains=None)` — both args are optional, can be called with no args.
- `camel.toolkits.SearchToolkit.search_duckduckgo(self, query, source="text", number_of_result_pages=10)` — exists. Decorated with `@dependencies_required("ddgs")`. Imports `from ddgs import DDGS` at call time.
- `camel.toolkits.SearchToolkit.search_google(...)` — exists. Reads `GOOGLE_API_KEY` + `SEARCH_ENGINE_ID` from env at call time.
- `camel.toolkits.FunctionTool` has a `get_function_name() -> str` method. **Use this instead of** `tool.func.__name__`, which is unreliable.
- The `ddgs` package is already installed at `backend/.venv/lib/python3.10/site-packages/ddgs/`. No new dependency needs to be added.

**`create_browser_agent` call site** is `backend/app/services/agent_service.py:490`:
```python
browser_agent = create_browser_agent(task_lock, browser_model, working_dir)
```
The signature does not change in this plan, so the call site is untouched.

**How to run pytest in cape-agent:**
```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend
.venv/bin/python -m pytest tests/ -v
```
(There is no `conftest.py`, no `pytest.ini`, no `pyproject.toml [tool.pytest.ini_options]`. Tests are discovered via the default rules. The existing `tests/test_conversation_context.py` is the format reference.)

---

### Task 1: Create `SearchToolkit` with TDD

**Files:**
- Create: `/Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend/tests/test_search_toolkit.py`
- Create: `/Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend/app/toolkits/search_toolkit.py`

- [ ] **Step 1: Write the failing test file**

Create `backend/tests/test_search_toolkit.py` with this exact content:

```python
"""Tests for app.toolkits.search_toolkit.SearchToolkit.get_can_use_tools()."""

from app.toolkits.search_toolkit import SearchToolkit


class TestGetCanUseTools:
    def test_returns_google_when_both_keys_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        monkeypatch.setenv("SEARCH_ENGINE_ID", "fake-cx")
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_google"

    def test_returns_duckduckgo_when_no_google_keys(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_duckduckgo"

    def test_returns_duckduckgo_when_only_google_api_key_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_duckduckgo"

    def test_returns_duckduckgo_when_only_search_engine_id_set(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("SEARCH_ENGINE_ID", "fake-cx")
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_duckduckgo"
```

> Note: The spec showed three tests; this plan adds a fourth covering the symmetric "only `SEARCH_ENGINE_ID` set" branch. Both env vars must be present for Google to activate, so both branches matter.

- [ ] **Step 2: Run the tests and verify they fail**

Run:
```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend && .venv/bin/python -m pytest tests/test_search_toolkit.py -v
```

Expected output: All 4 tests FAIL with `ModuleNotFoundError: No module named 'app.toolkits.search_toolkit'`.

If you see a different error, stop and investigate before writing the implementation.

- [ ] **Step 3: Write the minimal `SearchToolkit` implementation**

Create `backend/app/toolkits/search_toolkit.py` with this exact content:

```python
"""Cape-agent search toolkit.

Thin wrapper around CAMEL-AI's SearchToolkit that exposes exactly one
search tool to the agent: `search_google` if Google Custom Search keys
are configured, otherwise `search_duckduckgo` as a zero-config fallback.
"""

import os

from camel.toolkits import FunctionTool
from camel.toolkits import SearchToolkit as CamelSearchToolkit


class SearchToolkit:
    """Picks Google or DuckDuckGo based on environment variables.

    The agent never sees both — exactly one search tool is registered,
    decided at agent-creation time.
    """

    @classmethod
    def get_can_use_tools(cls) -> list[FunctionTool]:
        camel = CamelSearchToolkit()
        if os.getenv("GOOGLE_API_KEY") and os.getenv("SEARCH_ENGINE_ID"):
            return [FunctionTool(camel.search_google)]
        return [FunctionTool(camel.search_duckduckgo)]
```

- [ ] **Step 4: Run the tests and verify they pass**

Run:
```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend && .venv/bin/python -m pytest tests/test_search_toolkit.py -v
```

Expected output: 4 passed.

If any test fails, do NOT modify the test to make it pass. Read the error, fix the implementation in `search_toolkit.py`, and rerun.

- [ ] **Step 5: Commit**

```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search && \
git add backend/app/toolkits/search_toolkit.py backend/tests/test_search_toolkit.py && \
git commit -m "feat(toolkits): add SearchToolkit wrapper with env-based provider selection

Picks search_google when GOOGLE_API_KEY + SEARCH_ENGINE_ID are set,
otherwise falls back to search_duckduckgo (zero-config). Mutually
exclusive: the agent only ever sees one search tool."
```

---

### Task 2: Wire `SearchToolkit` into `create_browser_agent`

**Files:**
- Modify: `/Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend/app/agents/factory/browser.py`

This task changes only the imports and the `tools = ...` assembly. Prompt rewrites are in Task 3.

- [ ] **Step 1: Add the import**

In `backend/app/agents/factory/browser.py`, add this import alongside the existing toolkit imports (around line 5):

```python
from app.toolkits.search_toolkit import SearchToolkit
```

The top of the file should now read:

```python
import platform
from datetime import datetime

from camel.messages import BaseMessage
from app.toolkits.terminal_toolkit import TerminalToolkit
from app.toolkits.search_toolkit import SearchToolkit

from app.agents.listen_chat_agent import ListenChatAgent
from app.services.browser_service import browser_service
from app.services.task_lock import TaskLock
```

- [ ] **Step 2: Append search tools to the tool list inside `create_browser_agent`**

Locate the section in `create_browser_agent` that builds `tools` (currently around lines 89–98). Replace:

```python
    tools = browser_service.get_tools()

    # Add terminal toolkit so the browser agent can save research results
    # to files (e.g., JSON, text summaries) in the working directory.
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
    )
    tools = tools + terminal_toolkit.get_tools()
```

with:

```python
    tools = browser_service.get_tools()

    # Add terminal toolkit so the browser agent can save research results
    # to files (e.g., JSON, text summaries) in the working directory.
    terminal_toolkit = TerminalToolkit(
        working_directory=working_directory,
        safe_mode=True,
        clone_current_env=True,
    )
    tools = tools + terminal_toolkit.get_tools()

    # Add a real search tool. Picks Google Custom Search when both
    # GOOGLE_API_KEY and SEARCH_ENGINE_ID are configured, otherwise
    # falls back to DuckDuckGo (zero-config). Exactly one search tool
    # is registered.
    tools = tools + SearchToolkit.get_can_use_tools()
```

- [ ] **Step 3: Smoke-import the modified factory**

Run:
```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend && \
.venv/bin/python -c "from app.agents.factory.browser import create_browser_agent; print('OK')"
```

Expected output: `OK`.

If you get an `ImportError`, the most likely cause is a circular import or a typo. Read the traceback carefully.

- [ ] **Step 4: Re-run the search toolkit tests to make sure nothing broke**

```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend && \
.venv/bin/python -m pytest tests/test_search_toolkit.py -v
```

Expected output: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search && \
git add backend/app/agents/factory/browser.py && \
git commit -m "feat(browser-agent): wire SearchToolkit into create_browser_agent

The browser agent now has a real search tool (search_google or
search_duckduckgo) in addition to the existing browser/terminal tools."
```

---

### Task 3: Rewrite the Browser Agent prompt for search-first workflow

**Files:**
- Modify: `/Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend/app/agents/factory/browser.py`

This task rewrites three prompt sections inside `BROWSER_SYSTEM_PROMPT`. Do them as one logical change but verify each replacement individually.

- [ ] **Step 1: Replace the URL POLICY paragraph in `<mandatory_instructions>`**

Inside `BROWSER_SYSTEM_PROMPT`, find and replace this exact block:

```
- URL POLICY: You may navigate to well-known search engines (google.com,
    bing.com, duckduckgo.com) and URLs provided by the user. For all other
    URLs, only use links found on webpages you have visited through the
    browser. Do NOT invent or guess specific article/page URLs.
```

with:

```
- CRITICAL URL POLICY: You are STRICTLY FORBIDDEN from inventing URLs.
    You MUST only use URLs from one of these sources:
      1. URLs returned by search tools (`search_google` /
         `search_duckduckgo`)
      2. URLs found on webpages you have visited via browser tools
      3. URLs explicitly provided by the user
    You MUST NOT navigate to search engine homepages (google.com,
    bing.com, duckduckgo.com) — use the search tools instead.
```

- [ ] **Step 2: Replace the entire `<web_search_workflow>` section**

Find and replace this exact block (currently lines ~63–82):

```
<web_search_workflow>
You perform ALL web searches by navigating the browser directly to search
engines. Follow this workflow:

1. Use `browser_visit_page("https://www.bing.com")` to open Bing
   (or duckduckgo.com as alternative; avoid Google — it often blocks
   automated access).
2. Use `browser_type` to enter your search query into the search box,
   then `browser_enter` to submit.
3. Use `browser_get_page_snapshot` to read the search results.
4. Click on promising result links with `browser_click`.
5. Use `browser_get_page_snapshot` to read page content. The output can
   be very large — focus on extracting only the relevant parts.
6. Interact with pages using `browser_click`, `browser_type`,
   `browser_select`, `browser_enter` as needed.

**When encountering verification challenges** (login, CAPTCHAs, robot
checks), note the issue and move on to alternative search engines or
sources.
</web_search_workflow>
```

with:

```
<web_search_workflow>
You have a dedicated search tool — USE IT FIRST. The browser is for
reading specific pages, not for typing queries into search boxes.

Standard workflow:
1. Call `search_google` (or `search_duckduckgo` — only one will be
   available depending on configuration) with a focused query. Returns
   a list of {title, url, description} results.
2. Pick 1–3 promising results and call `browser_visit_page(url)` to
   read the full content.
3. Use `browser_get_page_snapshot` to extract the relevant text. The
   output can be very large — focus on extracting only the relevant
   parts.
4. If a page requires interaction (login, click-to-expand, form), use
   `browser_click` / `browser_type` / `browser_select` / `browser_enter`.
5. If you need follow-up information, refine the query and call the
   search tool again — do NOT navigate to a search engine homepage.

**Fallback:** only if the search tool returns no useful results AND you
cannot form a better query, you may use `browser_visit_page` against
duckduckgo.com as a last resort.

**When encountering verification challenges** (login, CAPTCHAs, robot
checks), note the issue and pivot to a different result from your
search results.
</web_search_workflow>
```

- [ ] **Step 3: Trim the `<capabilities>` section**

Find this exact block (currently lines ~54–61):

```
<capabilities>
- Use the browser toolset to visit, navigate, and interact with websites.
- Navigate to search engines (google.com, bing.com, duckduckgo.com) to
  search for information.
- Use the terminal (shell_exec) to save research results to files in the
  working directory. For example, use `echo '...' > file.txt` or
  `python3 -c "import json; ..."` to write structured data.
</capabilities>
```

Replace with:

```
<capabilities>
- Use the search tool (`search_google` or `search_duckduckgo`) to find
  information on the web.
- Use the browser toolset to visit, navigate, and interact with specific
  webpages returned by the search tool.
- Use the terminal (shell_exec) to save research results to files in the
  working directory. For example, use `echo '...' > file.txt` or
  `python3 -c "import json; ..."` to write structured data.
</capabilities>
```

The "Navigate to search engines" line is removed because the new URL policy forbids it.

- [ ] **Step 4: Smoke-import the modified factory and inspect the prompt**

Run:
```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend && \
.venv/bin/python -c "
from app.agents.factory.browser import BROWSER_SYSTEM_PROMPT
assert 'CRITICAL URL POLICY' in BROWSER_SYSTEM_PROMPT, 'URL policy not updated'
assert 'USE IT FIRST' in BROWSER_SYSTEM_PROMPT, 'workflow not updated'
assert 'Navigate to search engines' not in BROWSER_SYSTEM_PROMPT, 'capabilities not trimmed'
assert 'browser_visit_page(\"https://www.bing.com\")' not in BROWSER_SYSTEM_PROMPT, 'old workflow remnant'
print('OK')
"
```

Expected output: `OK`.

If any assertion fails, the corresponding replacement was not applied correctly. Re-read the file and fix the section that failed.

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend && \
.venv/bin/python -m pytest tests/ -v
```

Expected output: All tests pass (the existing `test_conversation_context.py` tests + the 4 new search toolkit tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search && \
git add backend/app/agents/factory/browser.py && \
git commit -m "feat(browser-agent): rewrite prompt for search-first workflow

- Replace 6-step browser-scrape-bing workflow with search-tool-first
  flow: call search_google/search_duckduckgo, then browser_visit_page
  on selected URLs.
- Tighten URL policy: forbid inventing URLs and forbid navigating to
  search engine homepages.
- Trim capabilities to remove the now-forbidden 'navigate to search
  engines' affordance."
```

---

### Task 4: Add `backend/.env.example`

**Files:**
- Create: `/Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend/.env.example`

- [ ] **Step 1: Create the file**

Create `backend/.env.example` with this exact content:

```
# Cape Agent backend environment variables.
# Copy this file to backend/.env and fill in the values you want to use.
# All values are optional — the app runs without any of them.

# --- Web search (optional) ---
#
# Cape Agent's Browser Agent uses a real search tool. By default it
# falls back to DuckDuckGo, which requires no configuration.
#
# For higher-quality results, set up Google Custom Search:
#   1. Get an API key:        https://console.cloud.google.com/apis/credentials
#   2. Create a Search Engine: https://programmablesearchengine.google.com/
#   3. Set both variables below.
#
# When BOTH are set, the Browser Agent uses Google. If either is
# missing, it falls back to DuckDuckGo.
#
# GOOGLE_API_KEY=
# SEARCH_ENGINE_ID=
```

- [ ] **Step 2: Verify `.env.example` is not already gitignored**

Run:
```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search && \
git check-ignore backend/.env.example && echo "IGNORED" || echo "NOT IGNORED"
```

Expected output: `NOT IGNORED`. (`.env` is typically gitignored, but `.env.example` should not be.)

If you see `IGNORED`, inspect `.gitignore` to see what's matching, and adjust the gitignore to exclude `.env.example` from the ignore rule.

- [ ] **Step 3: Commit**

```bash
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search && \
git add backend/.env.example && \
git commit -m "docs(backend): add .env.example documenting GOOGLE_API_KEY + SEARCH_ENGINE_ID"
```

---

### Task 5: Manual smoke test

This task is **manual** — no code changes. Run it after Task 4 commits, and report results back.

**Files:** none (manual verification only)

- [ ] **Step 1: Start the backend without any search keys (DuckDuckGo path)**

The simplest way is to launch the full Electron app from the repo root, which spawns the backend automatically. Make sure neither env var is set in your shell first:
```bash
unset GOOGLE_API_KEY SEARCH_ENGINE_ID
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search && \
npm run dev
```

Alternatively, run the backend standalone (it picks a free port starting at 8001 and prints it):
```bash
unset GOOGLE_API_KEY SEARCH_ENGINE_ID
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search/backend && \
.venv/bin/python main.py
```

- [ ] **Step 2: Trigger a research task and observe the tool calls**

In the Electron frontend chat (or via direct HTTP if running standalone), ask the Browser Agent something like:
> "Find the latest CAMEL-AI release version and summarize what's new."

In the backend logs / SSE stream, verify:
- The first tool call is `search_duckduckgo` (NOT `browser_visit_page` to a search engine homepage).
- Subsequent calls are `browser_visit_page` to URLs returned by the search.
- The agent never visits `bing.com`, `google.com`, or `duckduckgo.com` homepages.

- [ ] **Step 3: Restart the backend with Google keys (Google path)**

Stop the current process. Set both env vars (using real keys you control) in the same shell, then restart with the same command from Step 1:
```bash
export GOOGLE_API_KEY="your-real-key-here"
export SEARCH_ENGINE_ID="your-real-cx-here"
cd /Users/didi/Documents/opensource/cape-agent/.worktrees/feature-add-web-search && \
npm run dev
```

- [ ] **Step 4: Re-run the same query and verify Google is used**

In the logs, verify:
- The first tool call is now `search_google` (NOT `search_duckduckgo`).
- The agent does not visit any search engine homepage.

- [ ] **Step 5: Report results**

Report back which combinations worked and which (if any) showed unexpected behavior. If the LLM violated the URL policy (e.g., still visited bing.com), capture the exact prompt response and we'll iterate on the prompt wording in a follow-up.

---

## Definition of Done

After Task 4 commits and Task 5 reports clean:

- [x] `backend/app/toolkits/search_toolkit.py` exists, importable, 4 tests passing
- [x] `backend/app/agents/factory/browser.py` registers exactly one search tool and has the rewritten prompt
- [x] `backend/.env.example` documents the two env vars
- [x] `backend/tests/test_search_toolkit.py` passes (4 tests)
- [x] Manual smoke test confirms DuckDuckGo path works without keys
- [x] Manual smoke test confirms Google path works with keys
- [x] Browser Agent does not visit any search-engine homepage during a research task

Total commits expected: **4** (one per code task; Task 5 is manual and produces no commit).
