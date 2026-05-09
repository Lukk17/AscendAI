# Agent Standards & OpenSpec

This project imports a central set of AI agent standards (skills, commands, settings) from a shared repo, and uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven feature work.

---

## Agent standards import

The central AI standards are imported into this project via Git selective checkout. Only the required AI folders and template files are extracted directly into the project root. To protect the central repository, the remote is configured as read-only — its push URL is set to an invalid address so updates can be pulled but pushes are blocked.

### Step 1 — Initial setup

Enable symlink support in Git (globally, or just for this repo):

```shell
git config --global core.symlinks true
# or
git config core.symlinks true
```

Add the read-only remote and extract the standards:

```bash
git remote add agent-standards https://github.com/Lukk17/agent-standards
git remote set-url --push agent-standards no_push
git fetch agent-standards
git checkout agent-standards/master -- .agents .claude .kilocode .opencode .codex AGENTS.md.example kilo.jsonc.example opencode.json.example
git commit -m "Import central agent-standards (.agents and .claude)"
```

### Step 2 — Pulling future updates

```bash
git fetch agent-standards
git checkout agent-standards/master -- .agents .claude
git commit -m "Update AI standards from central repository"
```

---

## OpenSpec integration

OpenSpec installs skills and commands into each agent's native directories.

### How the symlinks work with OpenSpec

`.kilocode/skills/`, `.opencode/skills/`, and `.codex/skills/` are all symlinked to `.agents/skills/`. When `openspec init` writes skills to any of these directories, they land in `.agents/skills/` — the canonical location read by all agents.

Commands are tool-specific (different formats per agent) and cannot be centralized. OpenSpec creates them in each tool's native commands directory, which is expected and correct.

### Initializing OpenSpec

After running Step 1 above:

```bash
# Install OpenSpec globally
npm install -g @fission-ai/openspec@latest

# Initialize with all agents
# Skills land in .agents/skills/ via existing symlinks
# Commands are created in each tool's native commands directory
openspec init --tools "claude,kilocode,opencode,codex"
```

What `openspec init` creates:

```text
openspec/
  config.yaml              # OpenSpec project config
  specs/                   # Living documentation of your system
  changes/                 # Active feature work
    archive/               # Completed changes

# Skills (via symlinks, all land in .agents/skills/):
.agents/skills/openspec-workflow/SKILL.md
.agents/skills/openspec-specs/SKILL.md

# Commands (tool-specific, not symlinked):
.claude/commands/opsx/propose.md
.kilocode/workflows/opsx-propose.md
.opencode/commands/opsx-propose.md
```

Restart IDE and terminal after initialization.

### Tool directories reference

| Tool | Skills written to | Commands written to |
|---|---|---|
| Claude Code | `.claude/skills/openspec-*/` → `.agents/skills/` | `.claude/commands/opsx/*.md` |
| Kilo Code | `.kilocode/skills/openspec-*/` → `.agents/skills/` | `.kilocode/workflows/opsx-*.md` |
| OpenCode | `.opencode/skills/openspec-*/` → `.agents/skills/` | `.opencode/commands/opsx-*.md` |
| Codex | `.codex/skills/openspec-*/` → `.agents/skills/` | `$CODEX_HOME/prompts/opsx-*.md` |

### Command syntax variations

OpenSpec generates files for two different agent architectures:

- **Standalone Markdown commands** — agents that read flat files show commands with extensions (e.g. `/opsx-propose.md`).
- **Agent skills** — agents that parse semantic `SKILL.md` metadata or have native integration use slash syntax (e.g. `/opsx:propose`).

Use whichever syntax appears in your agent's autocomplete menu.

---

## OpenSpec workflow

### 0. Run the coding agent

```shell
claude
```

### 1. Propose a change

```text
/opsx:propose add dark mode support
```

```text
/opsx-propose.md add dark mode support
```

The agent creates the proposal, design, and implementation tasks under `openspec/changes/`.

### 2. Apply the code

Review the generated `tasks.md` (edit directly or have the agent revise it). Then:

```text
/opsx:apply
```

```text
/opsx-apply.md
```

The agent writes the code and checks off boxes in `tasks.md`.

### 3. Verify and refine

If bugs occur or tests fail, pass logs back:

```text
/opsx:verify The toggle button is invisible on mobile. Fix it.
```

```text
/opsx-verify.md The toggle button is invisible on mobile. Fix it.
```

### 4. Archive the change

```text
/opsx:archive
```

```text
/opsx-archive.md
```

The agent merges delta specs into `openspec/specs/` and moves the change folder to `openspec/changes/archive/`.
