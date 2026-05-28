# Refreshing shared agent tooling

---

[agent-standards](https://github.com/Lukk17/agent-standards) is upstream for [.agents/skills/](../.agents/skills/),
[.claude/agents/](../.claude/agents/), [.opencode/agents/](../.opencode/agents/), [AGENT_TOOLING.md](AGENT_TOOLING.md),
and [MCP_SETUP.md](MCP_SETUP.md).

The bootstrap import in [AGENT_TOOLING.md](AGENT_TOOLING.md) pulls everything from upstream. That is fine the first
time. On every later update it re-adds skills and subagents you removed on purpose.

The command below refreshes only what is already in the working tree. Skills added locally that do not exist upstream
stay untouched. Skills deleted locally stay deleted. [.claude/skills](../.claude/skills) and
[.opencode/skills](../.opencode/skills) are symlinks into [.agents/skills/](../.agents/skills/), so they update with
it.

To pull a brand-new upstream skill or subagent, run a one-off `git checkout agent-standards/master -- <path>` first.
Later refreshes will then keep it current.

Run from the repo root. Review `git diff --stat` afterwards. Commit when satisfied. Errors from paths that do not
exist upstream are swallowed by the stderr redirects.

**Bash:**

```bash
git fetch agent-standards && git checkout agent-standards/master -- docs/AGENT_TOOLING.md docs/MCP_SETUP.md && for d in .agents/skills/*/; do git checkout agent-standards/master -- "$d" 2>/dev/null; done && for f in .claude/agents/*.md; do git checkout agent-standards/master -- "$f" 2>/dev/null; done && for f in .opencode/agents/*.md; do git checkout agent-standards/master -- "$f" 2>/dev/null; done
```

**PowerShell 7+:**

```powershell
git fetch agent-standards && git checkout agent-standards/master -- docs/AGENT_TOOLING.md docs/MCP_SETUP.md && (Get-ChildItem .agents/skills -Directory | ForEach-Object { git checkout agent-standards/master -- ".agents/skills/$($_.Name)" 2>$null }) && (Get-ChildItem .claude/agents -Filter *.md | ForEach-Object { git checkout agent-standards/master -- ".claude/agents/$($_.Name)" 2>$null }) && (Get-ChildItem .opencode/agents -Filter *.md | ForEach-Object { git checkout agent-standards/master -- ".opencode/agents/$($_.Name)" 2>$null })
```
