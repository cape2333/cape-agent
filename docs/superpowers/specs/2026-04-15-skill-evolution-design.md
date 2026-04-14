# Skill Self-Evolution System Design

Cape Agent skill system that enables agents (browser, developer, document) to create, improve, and reuse skills through continuous usage. File-based storage inspired by Hermes Agent, adapted for Cape's multi-agent workforce architecture.

## Architecture Overview

### Storage Location

`~/.cape-agent/skills/` — sibling to existing `workspace/` and `browser_profiles/`.

### Directory Structure

```
~/.cape-agent/skills/
├── browser/
│   ├── google-scholar-search/
│   │   ├── SKILL.md
│   │   ├── references/
│   │   ├── templates/
│   │   └── scripts/
│   └── cloudflare-bypass/
│       └── SKILL.md
├── developer/
│   └── pytest-debug-workflow/
│       └── SKILL.md
├── document/
│   └── excel-pivot-workflow/
│       └── SKILL.md
├── .snapshot.json
└── .log/
    ├── 2026-04/
    │   └── events.jsonl
    ├── insights-pending.jsonl
    └── stats.json
```

- First-level directories are agent types: `browser`, `developer`, `document`.
- Each skill is a directory containing `SKILL.md` plus optional `references/`, `templates/`, `scripts/`.
- `.snapshot.json` caches the skill index for fast system prompt injection.
- `.log/` stores execution logs, pending insights, and aggregated stats.

### New Backend Modules

```
backend/app/
├── services/
│   ├── skill_service.py        # CRUD + index + snapshot cache
│   ├── skill_reviewer.py       # Post-task background review agent
│   └── skill_logger.py         # Execution log writes + stats aggregation
├── toolkits/
│   └── skill_toolkit.py        # Agent tools: skill_view / skill_manage / mark_insight
├── api/
│   └── skills.py               # Frontend REST API
└── models/
    └── skill_schemas.py        # Pydantic models
```

## Skill Format (SKILL.md)

### Frontmatter Schema

```yaml
---
name: google-scholar-search
description: "Google Scholar academic paper search optimization"
agent_type: browser                    # browser | developer | document
version: 1                            # integer, auto-incremented on patch/edit
enabled: true
created_by: agent                      # agent | user
created_at: "2026-04-15T10:30:00Z"
updated_at: "2026-04-15T10:30:00Z"
tags: [search, academic, google]       # optional
---
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Globally unique, matches directory name, `^[a-z0-9][a-z0-9._-]*$`, max 64 chars |
| `description` | yes | One-line summary for system prompt index, max 512 chars |
| `agent_type` | yes | `browser` / `developer` / `document` |
| `version` | yes | Integer, auto-managed |
| `enabled` | yes | Default true, toggleable from frontend |
| `created_by` | yes | `agent` (auto-created) or `user` (manual) |
| `created_at` | yes | ISO 8601 timestamp |
| `updated_at` | yes | ISO 8601 timestamp |
| `tags` | no | List of string tags for filtering |

### Body Structure (recommended, not enforced)

```markdown
## Trigger Conditions
When to use this skill.

## Steps
1. Step one with exact commands
2. Step two...

## Pitfalls
- Known issues and edge cases

## Verification
- How to confirm success
```

### Constraints

- name: `^[a-z0-9][a-z0-9._-]*$`, max 64 characters
- description: max 512 characters
- total content: max 50,000 characters
- supporting files in `references/`, `templates/`, `scripts/` subdirectories

## Agent Integration

### System Prompt Injection

On workforce startup, each agent's system prompt gets a skill index block appended. Only skills matching the agent's type and `enabled: true` are included. The index is read from `.snapshot.json` (no directory scan at request time).

Injected format:

```
## Available Skills

Before executing your task, scan the skills below. If any skill matches
your current task, load it with skill_view(name) and follow its instructions.

<available_skills>
- google-scholar-search: Google Scholar academic paper search optimization
- cloudflare-bypass: Cloudflare anti-bot verification bypass strategy
</available_skills>

If a skill you used was wrong or incomplete, update it with skill_manage.
After completing a difficult task (3+ tool calls with retries),
consider saving the approach as a new skill.
```

Only name + description are injected (minimal tokens). Agent calls `skill_view` for full content.

### Skill Toolkit

Registered in each agent factory (`factory/browser.py`, `factory/developer.py`, `factory/document.py`).

**`skill_view(name, file_path?)`**
- Reads SKILL.md full content for the named skill.
- Optional `file_path` to load supporting files (e.g., `references/api.md`).
- Returns markdown content.

**`skill_manage(action, name, content?, old_string?, new_string?)`**
- `create`: Validate frontmatter, write SKILL.md, refresh snapshot.
- `patch`: Find-and-replace within SKILL.md, auto-increment version.
- `edit`: Full rewrite of SKILL.md.
- `delete`: Remove skill directory.

**`mark_insight(agent_type, summary, context?)`**
- Lightweight recording during task execution.
- Appends to `.log/insights-pending.jsonl`.
- Does not create or modify skills directly.
- Format: `{"agent_type": "browser", "summary": "...", "context": "...", "conversation_id": "abc-123", "timestamp": "..."}`

### Scope

Only workforce agents (browser, developer, document) get skill integration. Simple path (direct ChatAgent) does not inject skills.

### Edge Cases

- **No skills exist yet**: Skill index block is omitted from system prompt entirely (no empty `<available_skills>` tag).
- **Review agent model/api_key**: Uses the same provider, model, and api_key from the user's current request (passed through `chat.py` → `skill_reviewer.review()`).
- **Concurrent writes to `insights-pending.jsonl`**: Use append mode with newline-terminated JSON. Each `mark_insight` call writes one atomic line. Review clears processed entries by rewriting the file excluding processed conversation_id entries (with file lock).

## Evolution Mechanics

### Real-time Marking (During Execution)

Agents call `mark_insight` when they:
- Retry with a different approach and succeed
- Discover a pitfall or workaround
- Find an existing skill's instructions wrong or incomplete

Guided by system prompt instruction:

```
When you encounter these situations during task execution:
- A retry with a different approach succeeded
- You discovered a pitfall or workaround
- An existing skill's instructions were wrong or incomplete

Call mark_insight() to record what you learned.
Do NOT stop to create a full skill — just record the observation and continue your task.
```

### Post-task Review (Background)

Triggered after workforce completion, only when pending insights exist for the conversation.

Flow:
1. Read `.log/insights-pending.jsonl` entries for the conversation_id.
2. Load existing skill index for relevant agent_types.
3. Build review prompt with insights + existing skills + task summary.
4. Run a lightweight ChatAgent with `skill_manage` tool.
5. Review agent decides per insight: patch existing skill / create new skill / discard.
6. Clear processed insights from pending file.
7. Refresh `.snapshot.json`.
8. Write events to execution log.

Implementation in `backend/app/services/skill_reviewer.py`:

```python
async def review(conversation_id, agent_types, task_summary):
    insights = read_pending_insights(conversation_id)
    if not insights:
        return

    existing_skills = load_skill_index(agent_types)
    prompt = build_review_prompt(insights, existing_skills, task_summary)

    reviewer = build_review_agent(model, api_key)
    result = await reviewer.astep(prompt)

    mark_insights_processed(conversation_id)
    refresh_snapshot()
```

Review prompt structure:

```
You are reviewing task execution insights to maintain the skill library.

## Task Summary
{task_summary}

## Pending Insights
{insights as numbered list}

## Existing Skills for {agent_type}
{skill names + descriptions}

For each insight, decide:
1. If it improves an existing skill -> use skill_manage(action="patch", ...)
2. If it's a new reusable approach -> use skill_manage(action="create", ...)
3. If it's too specific or trivial -> skip it

Only save knowledge that will help future tasks. Be selective.
```

Triggered from `chat.py` after workforce SSE `done` event:

```python
background_tasks.add_task(
    skill_reviewer.review,
    conversation_id=conversation_id,
    agent_types=["browser", "developer", "document"],
    task_summary=final_result_summary,
)
```

## Snapshot Cache

### `.snapshot.json` Structure

```json
{
  "generated_at": "2026-04-15T10:30:00Z",
  "manifest": {
    "browser/google-scholar-search/SKILL.md": "1713171000:2048",
    "browser/cloudflare-bypass/SKILL.md": "1713172000:1536"
  },
  "skills": [
    {
      "name": "google-scholar-search",
      "description": "Google Scholar academic paper search optimization",
      "agent_type": "browser",
      "enabled": true,
      "version": 2,
      "tags": ["search", "academic", "google"],
      "created_by": "agent"
    }
  ]
}
```

`manifest` maps each SKILL.md relative path to `mtime_ns:size` for staleness detection.

### Validation Logic

```python
def is_stale(snapshot) -> bool:
    for path, recorded in snapshot["manifest"].items():
        actual = f"{stat.st_mtime_ns}:{stat.st_size}"
        if actual != recorded:
            return True
    disk_paths = scan_skill_md_paths()
    if set(disk_paths) != set(snapshot["manifest"].keys()):
        return True
    return False
```

### Refresh Triggers

| Trigger | Method |
|---------|--------|
| `skill_manage` create/edit/patch/delete | Incremental update (changed skill only) |
| Frontend API modifies skill | Incremental update |
| Agent startup reads index | Validate manifest, full rebuild if stale |
| `.snapshot.json` missing | Full scan and rebuild |

## Execution Logging

### Event Log (`.log/YYYY-MM/events.jsonl`)

```json
{"event": "skill_loaded", "skill": "google-scholar-search", "agent_type": "browser", "conversation_id": "abc-123", "ts": "2026-04-15T10:30:00Z"}
{"event": "skill_created", "skill": "cloudflare-bypass", "agent_type": "browser", "created_by": "review", "ts": "2026-04-15T10:35:00Z"}
{"event": "skill_patched", "skill": "google-scholar-search", "agent_type": "browser", "version": 2, "ts": "2026-04-15T10:36:00Z"}
```

### Aggregated Stats (`.log/stats.json`)

```json
{
  "google-scholar-search": {"loads": 12, "patches": 2, "last_used": "2026-04-15"},
  "cloudflare-bypass": {"loads": 3, "patches": 0, "last_used": "2026-04-14"}
}
```

Updated incrementally on each log write.

## Frontend

### REST API (`backend/app/api/skills.py`)

```
GET    /api/skills                       # List (supports ?agent_type=&enabled=&tag=)
GET    /api/skills/{name}                # Detail (frontmatter + body + files list)
POST   /api/skills                       # Create
PUT    /api/skills/{name}                # Full update
PATCH  /api/skills/{name}                # Partial update (enabled/tags/description)
DELETE /api/skills/{name}                # Delete

GET    /api/skills/{name}/files          # List supporting files
GET    /api/skills/{name}/files/{path}   # Read supporting file
PUT    /api/skills/{name}/files/{path}   # Write supporting file
DELETE /api/skills/{name}/files/{path}   # Delete supporting file

GET    /api/skills/stats                 # Aggregated stats from stats.json
GET    /api/skills/logs                  # Recent events (?limit=50&skill=xxx)
```

### Pydantic Models (`backend/app/models/skill_schemas.py`)

```python
class SkillMeta(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    version: int
    enabled: bool
    created_by: Literal["agent", "user"]
    created_at: str
    updated_at: str
    tags: list[str] = []

class SkillDetail(SkillMeta):
    content: str          # markdown body after frontmatter
    raw: str              # full SKILL.md text including frontmatter
    files: list[str]      # supporting file relative paths

class SkillCreate(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    content: str
    tags: list[str] = []

class SkillUpdate(BaseModel):
    description: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None

class SkillStats(BaseModel):
    name: str
    loads: int
    patches: int
    last_used: str | None

class SkillLogEntry(BaseModel):
    event: str
    skill: str
    agent_type: str
    conversation_id: str | None
    timestamp: str
```

### Frontend Pages

**Skills list** (`/skills`):
- Filter by agent_type tabs (Browser / Developer / Document)
- Search by name/description/tags
- Each card shows: name, description, version, enabled toggle, load count, created_by badge
- [+ New Skill] button

**Skill detail** (`/skills/:name`):
- Header: agent_type, version, created_by, tags, enabled toggle, stats
- Body: rendered markdown content
- Supporting files list
- [Edit] and [Delete] buttons

**Skill edit** (`/skills/:name/edit` and `/skills/new`):
- Simple textarea for markdown content
- Form fields for name, description, agent_type, tags
- Save calls `PUT /api/skills/{name}` or `POST /api/skills`

### Store Extension (`store.ts`)

```typescript
skills: SkillMeta[]
activeSkill: SkillDetail | null
skillStats: Record<string, SkillStats>

fetchSkills(agentType?: string): void
fetchSkillDetail(name: string): void
createSkill(data: SkillCreate): void
updateSkill(name: string, data: SkillUpdate): void
deleteSkill(name: string): void
toggleSkillEnabled(name: string): void
```

### SSE Event Extensions

Three new event types through existing SSE channel during workforce execution:

```json
{"step": "skill_loaded", "data": {"skill": "google-scholar-search", "agent": "browser"}}
{"step": "insight_marked", "data": {"agent": "browser", "summary": "Scholar needs 5s delay..."}}
{"step": "skill_evolved", "data": {"action": "patched", "skill": "google-scholar-search", "version": 3}}
```

### Frontend Routes

```
/skills              -> Skill list page
/skills/:name        -> Skill detail page
/skills/new          -> Create skill page
/skills/:name/edit   -> Edit skill page
```
