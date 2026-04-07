# Web Search for Browser Agent — Design

**Date:** 2026-04-07
**Branch:** `feature-add-web-search`
**Status:** Approved (pending implementation)

## Goal

Give cape-agent's Browser Agent a real web-search tool instead of forcing it to drive the browser to a search-engine homepage and click around. Search-first, browser-second.

## Background

Today, `backend/app/agents/factory/browser.py` instructs the Browser Agent to perform web search by navigating Playwright/CDP to bing.com, typing into the search box, and scraping results. This is slow, brittle, and frequently blocked by anti-bot measures. Eigent solves the same problem by exposing CAMEL-AI's `SearchToolkit.search_google` directly to its browser/research agents, with a cloud proxy as fallback.

Cape-agent has no cloud proxy, so we use DuckDuckGo (zero-config, no API key) as the fallback for users who haven't configured a Google Custom Search key.

## Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Search providers | Google Custom Search + DuckDuckGo (zero-config fallback) |
| 2 | Provider exposure | **Mutually exclusive**: if Google keys are present, only `search_google` is registered; otherwise only `search_duckduckgo`. The agent never sees both. |
| 3 | Agents that get search | **Browser Agent only.** Developer and Document agents are unchanged. |
| 4 | Workflow positioning | Search-first, browser-second. The browser is for reading specific pages, not for typing queries into search boxes. |
| 5 | Configuration | Environment variables (`GOOGLE_API_KEY` + `SEARCH_ENGINE_ID`). Reading from `AppSettings` is deferred until the frontend Settings UI lands, to avoid dead schema fields. |
| 6 | URL policy | **Strict.** The agent must only use URLs returned by search tools, found on browser-visited pages, or supplied by the user. Navigating to search-engine homepages is forbidden. |

## Architecture

```
create_browser_agent()
  ├── browser_service.get_tools()         (existing)
  ├── TerminalToolkit.get_tools()         (existing)
  └── SearchToolkit.get_can_use_tools()   (NEW)
                │
                ▼
   app/toolkits/search_toolkit.py  (NEW)
   ┌──────────────────────────────────┐
   │ class SearchToolkit:             │
   │   @classmethod                   │
   │   def get_can_use_tools():       │
   │     if GOOGLE_API_KEY            │
   │        and SEARCH_ENGINE_ID:     │
   │       return [search_google]     │
   │     else:                        │
   │       return [search_duckduckgo] │
   └──────────────────────────────────┘
                │ delegates to
                ▼
   camel.toolkits.SearchToolkit
   (CAMEL-AI built-in)
```

**Key choices:**
- Tool resolution happens **at agent creation time**, not per-call. Env vars don't change at runtime in practice, so a fresh check per call is wasted work.
- Cape-agent's `SearchToolkit` **composes** CAMEL-AI's, it does not subclass it. Subclassing buys nothing here and adds method-override overhead.
- No cloud proxy, no thread-local user env, no `@listen_toolkit` telemetry — those exist in eigent for legitimate reasons that don't apply to cape-agent's simpler architecture.

## Components & File Changes

| # | File | Type | Change |
|---|---|---|---|
| 1 | `backend/app/toolkits/search_toolkit.py` | NEW | `SearchToolkit` class with `get_can_use_tools()` classmethod |
| 2 | `backend/app/agents/factory/browser.py` | MODIFY | Append search tools; rewrite `<web_search_workflow>`; tighten `<mandatory_instructions>` URL policy; adjust `<capabilities>` |
| 3 | `backend/.env.example` | NEW | Document `GOOGLE_API_KEY` and `SEARCH_ENGINE_ID` (file does not currently exist in backend/) |
| 4 | `backend/tests/test_search_toolkit.py` | NEW | Three unit tests for `get_can_use_tools()` branches |

### `SearchToolkit` interface

```python
# backend/app/toolkits/search_toolkit.py
import os
from camel.toolkits import SearchToolkit as CamelSearchToolkit
from camel.toolkits import FunctionTool


class SearchToolkit:
    """Cape-agent search toolkit. Picks Google or DuckDuckGo based on env."""

    @classmethod
    def get_can_use_tools(cls) -> list[FunctionTool]:
        camel = CamelSearchToolkit()
        if os.getenv("GOOGLE_API_KEY") and os.getenv("SEARCH_ENGINE_ID"):
            return [FunctionTool(camel.search_google)]
        return [FunctionTool(camel.search_duckduckgo)]
```

No instance state, no caching, no `__init__` parameters. The classmethod form is chosen for parity with eigent and to make future extension (e.g., taking a settings argument) non-breaking for callers.

### Browser Agent prompt changes

Two sections of `BROWSER_SYSTEM_PROMPT` are rewritten.

**A. `<mandatory_instructions>` — strict URL policy:**

```
CRITICAL URL POLICY: You are STRICTLY FORBIDDEN from inventing URLs.
You MUST only use URLs from one of these sources:
  1. URLs returned by search tools (search_google / search_duckduckgo)
  2. URLs found on webpages you have visited via browser tools
  3. URLs explicitly provided by the user
You MUST NOT navigate to search engine homepages (google.com, bing.com,
duckduckgo.com) — use the search tools instead.
```

This replaces the existing `URL POLICY:` paragraph.

**B. `<web_search_workflow>` — search-first workflow:**

```
You have a dedicated search tool — USE IT FIRST. The browser is for
reading specific pages, not for typing queries into search boxes.

Standard workflow:
1. Call `search_google` (or `search_duckduckgo` — only one will be
   available) with a focused query. Returns a list of {title, url,
   description} results.
2. Pick 1–3 promising results and call `browser_visit_page(url)` to
   read the full content.
3. Use `browser_get_page_snapshot` to extract the relevant text.
4. If a page requires interaction (login, click-to-expand, form), use
   `browser_click` / `browser_type` / `browser_select` / `browser_enter`.
5. If you need follow-up information, refine the query and call
   `search_*` again — do NOT navigate to a search engine homepage.

Fallback: only if `search_*` returns no useful results AND you cannot
form a better query, you may use `browser_visit_page` against
duckduckgo.com as a last resort.

When encountering verification challenges (CAPTCHAs, login walls), note
the issue and pivot to a different result from your search results.
```

This replaces the existing 6-step "navigate to bing.com" workflow.

**C. `<capabilities>`:** Remove the line that explicitly tells the agent to navigate to search engines, since the URL policy now forbids it.

Other prompt sections (`<role>`, `<team_structure>`, `<operating_environment>`) are unchanged.

## Data Flow

1. App startup: `create_browser_agent()` is called by `agent_service.py` when a chat task begins.
2. Inside the factory: `SearchToolkit.get_can_use_tools()` reads env once and returns a 1-element tool list.
3. The tool list is concatenated with browser tools and terminal tools, then passed to `ListenChatAgent`.
4. During chat: the LLM picks `search_google` (or `search_duckduckgo`), CAMEL-AI executes the call against Google's REST API (or DuckDuckGo via the `duckduckgo-search` library), and returns a list of `{title, url, description}` results.
5. The LLM picks promising URLs and calls `browser_visit_page(url)` to read full content.

## Error Handling

- **Search API failure** (network, rate limit, bad key): CAMEL-AI raises an exception; the tool result is propagated to the LLM as an error message; the LLM can retry with a different query or fall back to `browser_visit_page` per the prompt's fallback clause.
- **Missing keys at runtime**: cannot happen — we resolve at agent-creation time, so the agent always has exactly one search tool.
- **URL policy violation by the LLM**: enforced only at the prompt level. No programmatic guard. If we observe violations during smoke testing, we can revisit.

## Testing

### Unit tests — `backend/tests/test_search_toolkit.py`

```python
"""Tests for SearchToolkit.get_can_use_tools()."""

from camel.toolkits import FunctionTool
from app.toolkits.search_toolkit import SearchToolkit


class TestGetCanUseTools:
    def test_returns_google_when_both_keys_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        monkeypatch.setenv("SEARCH_ENGINE_ID", "fake-cx")
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].func.__name__ == "search_google"

    def test_returns_duckduckgo_when_no_google_keys(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].func.__name__ == "search_duckduckgo"

    def test_returns_duckduckgo_when_only_one_google_key_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
        tools = SearchToolkit.get_can_use_tools()
        assert tools[0].func.__name__ == "search_duckduckgo"
```

The test file uses `monkeypatch.setenv` / `monkeypatch.delenv` to isolate env state. The assertion on `tools[0].func.__name__` may need adjustment after we inspect CAMEL-AI's `FunctionTool` API (see Risks R2).

### Explicitly NOT tested

- CAMEL-AI's `search_google` / `search_duckduckgo` implementations — that's their responsibility.
- Real Google API calls — costs money, requires keys, breaks CI.
- Prompt string contents — fragile.
- End-to-end Browser Agent search behavior — depends on a non-deterministic LLM.

### Manual smoke test (after implementation)

1. Without keys: start the app, ask the Browser Agent to research "latest CAMEL-AI release". Expect it to call `search_duckduckgo`, then `browser_visit_page` on a result URL. Verify it never visits `bing.com` or `google.com` homepages.
2. With real `GOOGLE_API_KEY` + `SEARCH_ENGINE_ID`: restart, same query. Expect `search_google` instead.
3. Verify URL policy compliance in both runs by reading the agent step log.

## Risks

**R1. CAMEL-AI method names may vary across versions.** The DuckDuckGo method might be `search_duckduckgo` or `query_duckduckgo` or absent entirely.
*Mitigation:* Implementation step 1 is to grep the installed `camel/toolkits/search_toolkit.py` to confirm the actual method names and signatures. If DuckDuckGo is unavailable in the installed version, escalate to the user before proceeding (options: pin a newer CAMEL-AI version, or fall back to Google-only).

**R2. `FunctionTool.func.__name__` reflection may not work as written.** CAMEL-AI's `FunctionTool` could wrap the underlying callable in `functools.partial` or a custom wrapper, making `__name__` unreliable.
*Mitigation:* During implementation, inspect a real `FunctionTool` instance (`repr(tool)`, `dir(tool)`) and use the correct API — likely `tool.get_function_name()` or `tool.func.__wrapped__.__name__`. Adjust the test assertions accordingly.

**R3. CAMEL `SearchToolkit()` constructor may require arguments.** Some versions accept `timeout` / `exclude_domains`.
*Mitigation:* Read the CAMEL source before writing the wrapper. Pass empty defaults if required.

**R4. DuckDuckGo backend may need an extra Python package.** CAMEL-AI's DuckDuckGo support typically depends on the `duckduckgo-search` PyPI package.
*Mitigation:* Grep CAMEL's imports during implementation step 1. If missing, add to `backend/pyproject.toml`'s dependencies.

## Out of Scope

Explicitly **not** doing in this change:

- AppSettings schema extension or any database changes.
- Frontend Settings UI for search keys.
- NoteTakingToolkit integration.
- Adding the search tool to Developer / Document / Classifier agents.
- Other search providers (Tavily, Brave, Exa, Serper, Bing, Wikipedia).
- Configurable result count, timeout, or `exclude_domains` parameters.
- Telemetry / observability for search calls.
- Programmatic enforcement of the URL policy (prompt-level only).

These are deliberate YAGNI decisions; revisit only when a concrete need arises.

## Definition of Done

- [ ] `backend/app/toolkits/search_toolkit.py` exists and is importable.
- [ ] `backend/app/agents/factory/browser.py` registers the search tool and uses the rewritten prompt.
- [ ] `backend/.env.example` documents `GOOGLE_API_KEY` and `SEARCH_ENGINE_ID`.
- [ ] `backend/tests/test_search_toolkit.py` passes (3 tests).
- [ ] Manual smoke test passes for both DuckDuckGo and Google paths.
- [ ] Browser Agent does not visit any search-engine homepage during a research task.
