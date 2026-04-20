# Memory Rework: Implementation Spec

> Distilled from `memory-rework-dreaming-design.md`. Keep both; this one for coding.
> Status: ready to implement.

---

## 1. Core mechanic

Three phases, strict separation:
- **Live conversation** — converse, append transcript to current log, call recall tools.
- **Dreaming** — batch-process completed logs into atomic memory files + rebuilt index. Runs on boot only (v0), never during conversations.
- **Recall** — live LLM reads the index (always in prompt) and calls recall tools for details.

`save_memory` is removed. Memory creation is the dreamer's job.

---

## 2. Storage layout

```
$DATA_DIRECTORY/memory/
├── active_memory.md              # Index, injected into system prompt
├── memories/
│   └── YYYY-MM-DD_<slug>_<hex3>.md
└── logs/
    ├── pending/                  # All logs — live + not-yet-dreamed
    └── processed/                # Already dreamed
```

- Live logs write straight into `logs/pending/`. Currently-open file is tracked via in-process `_session_log_path` — dreamer skips it.
- Power-cut recovery: no lock files needed. On boot, dreamer processes everything in `pending/`.

---

## 3. Memory file format

```markdown
---
id: chess-openings_a3f
created: 2026-04-17T14:32:10Z
sources: [2026-04-14_09-15.log, 2026-04-15_21-04.log]
kind: preference          # fact | preference | event | skill | relationship | goal | other
tags: [chess, openings]   # first tag = primary (drives index grouping)
related_to: []            # sparse: only "must be read together" dependencies
pinned: false             # true for identity/core facts
supersedes: null          # memory ID this replaces
superseded_by: null       # memory ID that replaces this
---

# Chess openings discussion

Body, target 150-250 tokens. The dreamer chooses how to represent each fact — direct quotes (exact by nature), paraphrase, or compressed synthesis. The goal is faithful recall, not any particular style.
```

**Why each field:**
- `kind` (closed) drives update semantics (preferences overwrite, events append-only).
- `tags` (open) are the dynamic person-specific categorization — no folders needed.
- `related_to` is sparse dependency graph (not "all chess stuff" — that's tags).
- `pinned` keeps identity facts in the prompt forever — the "self-organizing" piece.
- `supersedes`/`superseded_by` replace silent overwrites with explicit replacement.

**ID format:** `YYYY-MM-DD_<slug>_<3-hex>`. ASCII only. Cross-platform safe.

---

## 4. Index format (`active_memory.md`)

```markdown
# Memory index

## Core (pinned)
- [user-name_01d] User's name is Rémi.

## Recent (last 30 days)
### Chess
- [chess-openings_a3f] Prefers Queen's Gambit; studying Catalan.
### Board games
- [board-game-night_b7c] Weekly Friday; last score 42-38.

## Older
Tags (count), ranked by frequency:
- work (8), family (5), travel (3), cooking (2), music (1)

Use `recall_topic(tag)` to load.
```

Regenerated atomically via `rebuild_index()` at end of every dream pass. Grouped by first tag.

**Older section gives the LLM real signal** — not just "there are old memories," but *what they're about* and *how much is there*. Ranking by count lets the LLM prioritize (a single `music` memory vs. 8 `work` memories). Count scope: Older memories only (Recent memories are already listed individually above). If distinct-tag count exceeds ~20, truncate to top-15 and add "… +N more tags."

---

## 5. Tools

### 5.1 Live conversation LLM — tools

These are the only tools the conversation LLM sees. **No dreaming-related tools in v0.**

| Tool | Signature | Returns |
|------|-----------|---------|
| `recall_memory` | `(id: str)` | Target memory **+ all memories in `related_to`** |
| `recall_topic` | `(tag: str, limit: int = 5)` | Memories matching tag, bounded |
| `short_term_memory` | `()` | Whole current session log, no filtering |

### 5.2 Dreamer — not a tool, a startup phase

The dreamer is **not exposed to the conversation LLM**. It is a pre-conversation phase: when the app starts, the dreamer runs to completion, then the conversation app boots. The live LLM has no awareness of dreaming — it just inherits a curated memory state.

The dreamer is itself an LLM with its own tool-calling interface (below). These tools exist so the dreamer can do its work; they are never visible to the conversation LLM.

**Logging requirement:** every step of the dream phase is printed to the terminal logger — every tool call, every LLM input/output, every decision. This is for debugging, not production telemetry. No silent success; no swallowed errors.

| Dreamer's tool | Signature |
|----------------|-----------|
| `read_log` | `(filename)` |
| `list_existing_memories` | `(tag=None, kind=None)` — returns id + one-line summary |
| `read_memory` | `(id)` |
| `write_memory` | `(id, content)` |
| `update_memory` | `(id, content)` |
| `rebuild_index` | `()` — regenerates `active_memory.md` from frontmatter |
| `mark_log_processed` | `(filename)` — moves `pending/foo.log` → `processed/foo.log` |

---

## 6. Dreamer prompt rules

These MUST live in the dreamer's system prompt. Highest leverage in the whole system.

1. **Atomicity** — One memory = one `kind` + one primary topic. If your draft has two, split it.
2. **Overlap-first** — Before creating, call `list_existing_memories(tag=X)` for each proposed tag. Prefer `update_memory` over `write_memory` when a same-topic memory exists.
3. **Evidence** — You choose how to represent each fact: direct quotes are fine (exact by nature, no further justification needed), paraphrasing and compression are fine *when you justify them in your reasoning output* with the source log quotes that back them. The rule is: no unjustified synthesis. If a memory is ever suspect, the dreamer's terminal log + the original session log are the audit trail. No cross-memory synthesis — don't merge facts from different memories into new claims; use `related_to` instead.
4. **Conflict** — New info contradicts old → set `supersedes`/`superseded_by`. Never silently overwrite.
5. **Pin** — `pinned: true` ONLY for identity/core (name, language, key relationships). When in doubt, don't pin.

---

## 7. Dreaming algorithm (v0)

Single-pass:

```python
stats = []
for log in sorted(logs/pending/*.log):
    if log == _session_log_path:
        continue
    t0 = time.monotonic()
    context = load_index() + load_all_memory_summaries() + load(log)
    result = call_dreamer(context)   # one LLM call, may chain tool calls internally
    apply(result)                    # write/update memory files
    mark_log_processed(log)
    stats.append(per_log_stats(log, t0, result))  # see §7.1

rebuild_index()
dreamer_self_reflection(stats)        # see §7.2
```

One log at a time, one LLM call per log. For later version maybe: upgrade path when index crosses ~80 memories: two-pass (extract proposals, then reconcile against filtered candidates). Tool signatures already support both.

### 7.1 Per-log benchmark

After every log is processed, print a one-line summary to the terminal logger:

```
[DREAM] 2026-04-15_21-04.log — 8.3s, 14 tool calls (read_log×1, list_existing×4, read_memory×2, write_memory×5, update_memory×2), created 5, updated 2, skipped 1
```

Captured metrics per log:
- Wall-clock duration (monotonic).
- Tool-call count, broken down by tool name.
- Outcome: memories created / updated / skipped.
- Any errors (with stack trace, never swallowed).

This is the baseline for judging whether dreamer latency is acceptable and whether the tool mix is healthy (e.g. a log with 50 `list_existing_memories` calls is a smell).

### 7.2 Self-reflection pass (end of dream phase)

After all logs are processed and the index is rebuilt, make one final LLM call asking the dreamer to reflect on its own run:

> You just processed N logs in total wall-time T. Here are the per-log stats: [stats].
> Based on this run, answer:
> 1. Were the available tools sufficient? Any task you wanted to do but couldn't?
> 2. Did the prompt's rules (atomicity, overlap-first, evidence, conflict, pin) fit the material? Any rule that was ambiguous or missing?
> 3. Any tool call you found yourself repeating unnecessarily — a sign a helper tool is missing?
> 4. Any concrete improvement you'd suggest.

Response is **printed to the terminal logger only**. Not stored in memory. Not acted on automatically. This is a feedback loop for Rémi to read between sessions — cheap signal for evolving the dreamer prompt and tool set over time.

---

## 8. Boot sequence

Strictly sequential. Conversation app does not start until dreaming finishes.

1. Mount memory directories.
2. Start dizzy-spin animation, loop it.
3. Run dream pass on `logs/pending/`. All steps printed to terminal logger. (On boot, `_session_log_path` is unset — everything in pending/ processes.)
4. Stop animation.
5. Boot conversation app.

If dreaming takes time, it takes time. The live LLM never touches the dreamer; it simply inherits the curated memory state once conversation starts.

---

## 9. Config

- `MEMORY_DREAMER_MODEL` env var. Default = live LLM model.
- Full dream-phase logging to console: every tool call, every LLM I/O visible.

---

## 10. Crash safety

- Log writes: append-only. Partial-line loss on crash = acceptable.
- Memory-file writes: write-temp-then-`os.replace`. Atomic on all three OSes.
- Index rebuild: same temp-then-replace. Always derived from frontmatter, so drift is self-healing.
- Concurrency: single asyncio loop. Dreamer never touches the file at `_session_log_path`.

---

## 11. Migration (fresh start)

- Wipe `active_memory.md`.
- Move existing `logs/*.log` → `logs/pending/`.
- Delete existing `archive/` directory.
- First boot dreams on all pending logs, rebuilds index from scratch.

---

## 12. Scope

Everything listed below is **in scope and must be implemented**. Nothing else.

- Memory file format with full frontmatter (§3).
- Tiered index rendering: Core / Recent / Older with ranked tag counts (§4).
- Live LLM tools: `recall_memory` (returns bundle), `recall_topic`, `short_term_memory` (§5.1).
- Dreamer as a blocking startup phase (§5.2, §8): prompt with the 5 rules (§6), its own tool set, dizzy-spin animation while running, full terminal logging, per-log benchmark (§7.1), end-of-run self-reflection pass (§7.2).
- `MEMORY_DREAMER_MODEL` env var, defaulting to the live LLM model (§9).
- Fresh-start migration (§11).
- Remove `save_memory` tool.

**Out of scope — do not implement, do not plan for:**
- Mid-conversation dreaming.
- Proactive background recall on index access.
- Two-pass dreamer (extract + reconcile). If the single-pass dreamer ever degrades with scale, revisit then — not before.

---

## References

- `memory-rework-dreaming-design.md` — full rationale, all the pushback and alternatives considered.
- [Letta filesystem benchmark](https://www.letta.com/blog/benchmarking-ai-agent-memory) — validates flat-on-disk.
- [Letta sleep-time compute](https://www.letta.com/blog/sleep-time-compute) — direct precedent for the dreaming concept. Worth 30 min before implementing.
