# Fresnel 0.4.0

- Adds repository-scoped durable task memory with deterministic event replay,
  sparse repository evidence, compressed artifacts, pinning, and 30-day raw
  retention.
- Unifies streamed and buffered completion, continues token-limited answers,
  retries transient transport failures, and resumes interrupted named sessions.
- Adds a clean terminal response lifecycle: ephemeral live draft, pinned
  `termtex` math conversion, Glow rendering, and successful interactive-only
  clipboard copy.
- Versions the orchestrator contract and adds adapter status, automatic safe
  sync, diff, and repair commands for Codex, Cursor, OpenCode, and generic tools.
- Adds health reporting for terminal helpers while retaining plain-Markdown
  fallback behavior.

All behavior is local by default. Fresnel does not copy piped/JSON output,
failed responses, or interrupted drafts, and never overwrites a modified
orchestrator adapter during automatic synchronization.
