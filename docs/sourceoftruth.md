# Felix's Tools — Source of Truth

This document is the canonical reference for the Felix's Tools project. Anyone or anything (including a fresh instance of an AI assistant) picking this project up should be able to read this file and understand what it is, why it's built the way it is, and what to do next — without needing prior conversation history.

## 1. What this is

Felix's Tools is a personal, modular, CLI-based toolkit for software development work — fullstack, research, and ML tasks. The intent is for it to be used indefinitely (not a weekend project), to stay usable as underlying models and techniques change, and to be extendable with new packages as new ideas come up. It's also designed so other solo developers could eventually use it, though that goal is explicitly secondary to it working well for its author (see Section 9, Non-goals).

The project consists of **four pieces of real software**: Logger, Brain, Router, Swarm — plus a **preset library** that Swarm executes. It is deliberately not a collection of "agent personalities" (many separate LLM-prompt-wrapped tools). See Section 2 for why that distinction matters and how it's enforced.

## 2. Core design philosophy

### 2.1 The litmus test

Before adding anything to this project, ask: **if you deleted the LLM call entirely, would anything be left?**

- If the answer is "no, it's just a prompt and a tool-loop" — it's not a new tool. It should be folded into Swarm as a **preset** (a config file describing a pipeline), not built as a standalone package.
- If the answer is "yes, there's a data structure, index, or algorithm that's useful on its own" — it qualifies as real tech and can be a package.

This is why the project has exactly four packages instead of eight-plus: ideas like "code review agent," "incident response agent," "flake triage agent," "docs-drift agent," and "paper-to-code agent" all failed this test on their own — they're LLM calls with no persistent structure underneath — so they live as **Swarm presets** that compose Logger + Brain + LLM calls, rather than as separate packages.

### 2.2 Build order and generalization discipline

- Build the bare-bones version of each piece first. Generalize a piece only when the bare-bones version demonstrably hurts in real use — not speculatively.
- **Rule of three**: don't add a shared abstraction until a third real use case actually needs it.
- Use each piece for real, daily work before building the next one. The point of building Logger and Brain before Swarm is to let real repeated manual workflows tell you what a Swarm preset actually needs to contain, instead of guessing at an orchestration abstraction with nothing real to test it against.
- Don't pre-build extensibility hooks for hypothetical future packages. Add structure when a real second or third package needs it.
- **"Demonstrably hurts" needs to be tracked, not vibed.** Keep a running plain-text friction log — a couple of lines each time something in the bare-bones version actually costs real time or produces a wrong answer (e.g. "2026-08-01: naive linking wired two unrelated `parse()` functions together, wasted 10 min," or "full rebuild took 47s on repo X, felt slow mid-task"). This is deliberately not a metrics system — a notes file is enough — but without writing these moments down as they happen, "only generalize once it demonstrably hurts" quietly turns into "whenever it feels like the right time," which defeats the point of the rule.

### 2.3 Human-in-the-loop is non-negotiable

Any preset step with an external side effect — opening a PR, posting to Slack, modifying a ticket, merging anything — requires a human approval gate. No autonomous action, no auto-merge. This applies regardless of how well-tested the preset is. This is a permanent constraint, not a "for now" one.

### 2.4 Governance check before first real-work use

Ticket-to-PR — the founding motivating use case for this whole project — implies pointing Swarm at real work tickets and source code fairly early, not eventually. If that happens, Router's cloud fallback could send that content to a third-party API. **Check company policy on tooling that sends code or ticket content to external APIs before running any preset against real work data, not after.** This is a one-time check, not an ongoing design concern, but it gates first real use rather than sitting at the end of the document as a someday item.

### 2.5 Independence and composition

Each package (Logger, Brain, Swarm) exposes interfaces that work completely standalone — no package requires another to function at a basic level:

- **CLI** — for direct human or script use. This is the day-one interface for every package, non-negotiable, since it's cheap and it's what actually delivers "independent" without any extra infrastructure.
- **Python library** — for fast, in-process calls from other packages in the monorepo (e.g. Swarm importing Brain directly, since both are Python — see Section 3.2).
- **MCP server** — added *per package, on demonstrated need*, not as day-one scaffolding for all three. Running three long-lived MCP server processes before any external agent host actually needs them would itself be premature infrastructure, which is exactly what Section 2.2 argues against everywhere else. The trigger to add a package's MCP server is a real moment where plugging it into Claude Code (or another host) directly would help — not "because modularity."

Independence specifics:
- Logger can run in a rule-based mode with no model calls at all.
- Brain's core graph queries need zero LLM involvement.
- Swarm can run a preset that never calls an LLM (pure orchestration over git/CI/tickets).
- Router is a plain internal library, not an MCP surface — it sits underneath model calls, deciding which backend answers, rather than being a tool an agent calls mid-conversation. Any package can call into it, but it is never a hard dependency and never gets its own MCP server.

**Where MCP fits and where it doesn't:** Swarm calls Brain and Logger as direct Python imports internally (same language, lowest latency) rather than routing through MCP between packages that already live in the same monorepo — MCP is for *external* consumption of a package, not internal calls between packages that are already Python function calls away from each other. The one place Swarm is itself an MCP client is for third-party systems that already ship their own MCP servers (GitHub, Atlassian/Jira) — a preset step calls those directly over MCP instead of hand-written API integration code. MCP is also not a fit for high-throughput internal loops: Logger's anomaly scorer, which scores every incoming log line, stays an internal process rather than going through MCP per line — MCP is for discrete request/response tool calls, not a data pipeline.

## 3. The four components

### 3.1 Logger

**What it is:** A fast local log search and anomaly detection system. Originally conceived as "a faster grep," but the actual value is not raw pattern-matching speed — ripgrep-class tools already win that comparison outright against any neural net. The real value is eliminating slow, repeated round trips to a big model during debugging, and catching patterns that regex fundamentally cannot (things nobody thought to search for).

**Components:**
1. **Parser/templater** — clusters raw log lines into templates (Drain-style log parsing), so structurally identical messages with different variable values collapse into one template. Pure classical algorithm, no ML.
2. **Structured index** — stores parsed templates with real fields (service, severity, template id, timestamp, variables), enabling fast filtered queries instead of full-text regex scans. Tags entries with the shared location/entity identifier from `common/` so Swarm presets can correlate a Logger anomaly with Brain's blast radius for the same location. Pure infra, no ML.
3. **Query planner** *(uses the trained model)* — translates a natural-language question into a small set of targeted, parallel structured queries against the index, similar to how WarpGrep plans grep calls for code search rather than doing the string matching itself. Needs to be small and local for interactive latency.
4. **Anomaly scorer** *(uses the trained model)* — runs continuously on incoming lines, flagging templates or frequency patterns that are statistically novel or spiking. This is the piece regex cannot replicate — you can't write a pattern for something that's never occurred before. Needs to be small for throughput reasons: it has to score every incoming line cheaply.

**Where the model does and doesn't fit:** only the query planner and anomaly scorer use a trained model. Parsing and indexing are classical, model-free components. This keeps the "delete the LLM, what's left" ratio high.

**Fine-tuning status:** the original motivation for post-training a small model here was to have a concrete project for learning RL-based post-training (specifically to get hands-on with PRIME-RL as a field). This is explicitly a **side project decoupled from Logger's core success** — Logger's core function should work fine against any decent stock small model (e.g. MiniCPM-1B or similar) with good prompting, with no fine-tuning required. When a better base model ships, the plan is to swap to it, not retrain — retraining is not part of the maintenance commitment for this project.

### 3.2 Brain

**What it is:** A persistent structural knowledge graph of a codebase, built via static analysis rather than by having an LLM read files. Gives deterministic, factual answers to structural questions that would otherwise require an LLM to guess from partial context.

**Decision: build in-house, not fork.** Mature MIT-licensed alternatives exist and were seriously evaluated (`colbymchenry/codegraph`, `DeusData/codebase-memory-mcp`, `sdsrss/code-graph-mcp`), plus a heavier one (`GitNexus`) that was ruled out specifically for using a custom graph database instead of SQLite and shipping under a PolyForm Noncommercial license — a real enough problem that at least one other team is known to have moved off it for that reason. The case for building anyway: none of the forks model git co-change history or code ownership as part of the graph, they're purely AST-structural, and that ownership/co-change layer is Brain's actual differentiator. Building in-house also doubles as a learning project, in the same spirit as Logger's fine-tuning side-quest.

**Where the real difficulty is, and where it isn't.** Parsing a single file with tree-sitter and extracting its functions, classes, and imports is genuinely easy. The hard part — and it's not optional polish, it's the substance of "blast radius" and "who calls this" — is resolving a call in one file to its real definition in another file. This is hard enough that GitHub built a dedicated library for exactly this problem (`tree-sitter-stack-graphs`, based on scope-graph theory from static-analysis research), and even that purpose-built tool has open reports of cross-file resolution not working cleanly in every case. The tempting shortcut — matching calls to definitions by name alone, with no import resolution — has a known failure mode: it silently produces wrong edges whenever two unrelated things share a name, even within a single language. This is a real, named risk, not a hypothetical one, and it's why the build order below treats it as a deliberate, temporary tradeoff rather than an oversight.

**Components:**
1. **Git co-change/ownership graph** — built directly from `git log`, no parsing involved. Answers "who owns this file" and "what usually changes alongside this file." The actual differentiator over the forks; build this first.
2. **Parser layer** — tree-sitter extraction of functions, classes, and imports, one language at a time.
3. **Call/import linking** — starts as naive name-based matching, with the same-name-collision risk above accepted knowingly. Escalates to proper import-aware resolution (`tree-sitter-stack-graphs`, or its early — currently work-in-progress and fork-dependent — Python bindings) only once naive linking is visibly wrong often enough in real use to justify the investment.
4. **Graph store** — SQLite (adjacency-list tables + recursive CTEs). Nodes are keyed by the same shared location/entity identifier from `common/` that Logger tags its entries with, so the two can be correlated by a Swarm preset without guesswork.
5. **Query API** — answers structural questions via graph traversal (blast radius, ownership, call graph). Exposed as a CLI and Python library from day one; gets an MCP server added once there's an actual reason to plug Brain into Claude Code or another agent host directly (Section 2.5). No natural-language-to-query translation layer is needed either way: any agent calling Brain is already an LLM and can emit a structured query directly, so Brain carries no model dependency at all, not even optionally.

**Incremental updates are explicitly deferred**, same reasoning as before — file-watching and incremental re-parsing (cache invalidation, renames, large branch switches) is real distributed-systems difficulty. Start with full rebuild on every run; only build incremental updates if a real repo proves that's too slow to use interactively.

**Build order specific to Brain** (fits into the overall sequence in Section 7):
1. Git co-change/ownership graph only — easy, high-value, ships first, and validates the "why build this instead of forking" reasoning immediately.
2. Single-language structural extraction (whichever language is used daily), full rebuild only.
3. Naive name-based call linking — deliberately approximate, used for real before investing further.
4. Proper import-aware resolution via stack-graphs — only if naive linking's false-positive rate actually becomes a problem in practice.
5. Additional languages and incremental re-indexing — deferred until a real need shows up (Section 9).

### 3.3 Router

**Decision: adopt LiteLLM, don't build backend abstraction from scratch.** LiteLLM's SDK mode (`from litellm import completion`) already provides one call shape across local and cloud model providers, with no server process required. That covers the hardest part of what Router was scoped to do. Router's remaining scope shrinks to a thin wrapper around that SDK call. LiteLLM's own Proxy Server mode (virtual keys, team budgets, Postgres, admin dashboard) was considered and rejected — that's enterprise/team complexity this project doesn't need. Other alternatives considered (Bifrost, Portkey, Kong AI Gateway, OpenRouter) are all aimed at team/production traffic, or in OpenRouter's case are a hosted service — routing local calls through third-party infrastructure would cut against the local-first design used everywhere else in this project.

**What it is now:** a thin wrapper around `litellm.completion`, not a package with its own backend-adapter code.

**Components:**
1. **Decision policy** — routes by task type (each caller tags its request, e.g. `log_query_planning`). Starts as simple rule-based mapping. A cascading pattern (try the small edge model first, escalate to a cloud model only when the small model signals low confidence) is a useful refinement but not required on day one — confidence signals from small models are an imperfect heuristic, not something to over-trust.
2. **Cache** — exact-match caching keyed on a hash of the normalized input, layered on top of the LiteLLM SDK call so repeated calls skip the model entirely. Semantic (similarity-based) caching is explicitly deferred.
3. **Backend abstraction and fallback/retry** — provided by `litellm` itself, not written in-house.

**Callers:** Logger's query planner and anomaly scorer, and Swarm's LLM reasoning steps in presets, call through this thin wrapper. Brain does not call through it at all — Brain has no model dependency (Section 3.2).

**Interface:** Router is a plain internal Python library, not an MCP server (see Section 2.5) — it sits underneath model calls rather than being a tool an agent calls mid-conversation.

**Maintenance note:** the one real exposed seam is upstream provider SDK/endpoint changes — now inherited from `litellm` itself rather than hand-written adapters, which if anything shrinks this maintenance surface further, since `litellm` tracks provider changes upstream on its own schedule.

### 3.4 Swarm

**What it is:** The orchestration engine. Takes a **preset** — a declarative pipeline definition, not new code — and executes it: a sequence or DAG of steps calling Logger, Brain, an LLM (via Router), and external systems (git, CI, ticketing), with state tracking, retries, and checkpointing.

**Why it's built last:** its whole job is orchestrating things that already exist. Building it before Logger and Brain exist means designing an abstraction against nothing real. The plan is to manually run workflows (e.g. stepping through an incident by hand, calling Logger and Brain directly) for a couple of weeks first, and let the repetitive parts define what a preset needs to contain.

**Idempotency/retry-safety is a first-class design concern**, not an afterthought — any step with a side effect (opening a PR, posting a message) must be safe to run twice, or a retry can double-post or duplicate an action. Lean on an existing orchestration framework's patterns rather than inventing retry semantics from scratch.

**MCP roles.** Swarm plays two different MCP roles, not one, and they follow different timelines. As a client, Swarm reaches third-party systems that already ship their own MCP servers (GitHub, Atlassian/Jira) instead of hand-writing API integration code for them — this is useful as soon as Swarm exists, since it's what keeps preset-writing cheap. As a server, exposing each preset as a callable tool (e.g. `run_preset(name="ticket-to-pr", ticket_id=...)`) so any MCP host — Claude Code included — can trigger a run directly follows the same on-demand rule as Brain and Logger's MCP servers (Section 2.5): build it once there's an actual reason to trigger a preset from inside an agent host, not as day-one scaffolding. Either way, Swarm still calls Brain and Logger as direct Python imports internally, not over MCP (Section 2.5). None of this relaxes the human-gating requirement in Section 2.3: MCP's host-level tool-approval is only visible in an interactive session, so a preset running unattended in the background still needs Swarm's own explicit approval-gate mechanism before any side-effecting step fires.

**Presets are config, not code.** Adding a new automated workflow means writing a new preset file, not a new package. Known preset ideas (not yet built, listed here so they aren't accidentally re-proposed as standalone packages later):
- **Ticket → PR** — the original motivating idea. Takes a ticket, scopes the change via Brain, drafts a fix, opens a PR (human-gated). Check Section 2.4's governance note before pointing this at real work tickets.
- **Code review** — on a PR, gets blast radius and ownership from Brain, checks Logger for historical error correlation in the touched area, then does a focused LLM review pass.
- **Incident response** — on an alert, queries Logger for anomalies and Brain for recent changes/blast radius in the affected area, then drafts a root-cause hypothesis and suggested fix (human-gated before any action).
- **Docs drift** — compares doc claims against Brain's structural ground truth, flags or drafts corrections (human-gated).
- **Flake triage** — classifies CI failures as flaky vs. real, quarantines flaky tests, files an issue with repro info.
- **Paper → code** — scaffolds an implementation and benchmark harness from a research paper or idea.

## 4. Repository structure

Single monorepo, `felixs-tools`, organized as packages rather than as one flat codebase:

```
felixs-tools/
  packages/
    common/     # shared types: task-type taxonomy, request/response schemas,
                # preset schema, Brain query result shape, and a shared
                # location/entity identifier (file path + optional service
                # label) so Logger and Brain can be correlated — build this first
    router/     # thin decision-policy + cache wrapper around litellm
    logger/     # parser, index, query planner, anomaly scorer
    brain/      # git co-change/ownership graph, AST parser, graph store, query API
    swarm/      # DAG executor + preset runner
  presets/      # ticket-to-pr.yaml, incident-response.yaml, etc.
  cli/          # `flx` entrypoint dispatching into each package
  .github/
    workflows/
      mirror.yml  # auto-mirrors swarm/logger/brain to standalone repos, see Section 5
```

Each package has its own dependency manifest, so someone (or a fresh checkout) can install just one piece without pulling in every dependency — e.g. Brain's tree-sitter dependency shouldn't be required to use Logger.

**Standalone mirror repos** (for anyone who wants just one piece, without cloning the monorepo):
- `mqnch/swarm`
- `mqnch/logger`
- `mqnch/brain`

Router and `common/` are **not mirrored** — they are internal monorepo libraries (Router is a thin LiteLLM wrapper, not a standalone tool).

`felixs-tools` is the **only place development happens**. The three mirror repos are read-only outputs, not separate places to commit.

## 5. Auto-mirroring setup

**Direction: one-way only, monorepo → mirrors.** This is intentional, not a limitation to fix later. True bidirectional auto-sync (mirror repo changes flowing back into the monorepo automatically) creates a real risk of trigger loops and silent conflict clobbering via force-push. If outside contribution to a mirror repo ever becomes real, the safe version of pulling it back in is a workflow that opens a **pull request** against the monorepo (via `git subtree pull` + a PR-creation step) rather than pushing directly — a human merge breaks any potential loop. This has not been built and should only be built once there's an actual external contributor on one of the mirrors.

**How the forward mirror works** (`.github/workflows/mirror.yml` in `felixs-tools`):
1. On every push to `main`, `dorny/paths-filter` detects which of `packages/{swarm,logger,brain}` changed.
2. For each changed mirrored package, `git subtree split --prefix=packages/<name>` extracts that directory's history onto a temporary branch.
3. That branch is force-pushed to the matching mirror repo's `main` branch, using a personal access token (stored as the `MIRROR_TOKEN` secret) with write access to the three mirror repos (`swarm`, `logger`, `brain`).
4. Unchanged packages are skipped entirely — editing `logger/` never touches `brain`'s mirror. Only `packages/{swarm,logger,brain}` are mirrored; `router/` and `common/` are ignored by the workflow.

Setup checklist:
- Create the `packages/{common,router,logger,brain,swarm}` directories with real content (import any existing code from the standalone repos via `git subtree add --prefix=packages/<name> <url> main`, if there's already something there).
- Create a PAT with write access to the three mirror repos, add it as `MIRROR_TOKEN` in `felixs-tools`'s Actions secrets.
- Place the mirror workflow in `.github/workflows/mirror.yml`.

**Consuming a mirror repo — always re-clone, never `git pull`.** Because the mirror workflow force-pushes `main` on every update, it rewrites history rather than appending to it. Anyone (including future-Felix on a different machine) who has already cloned a mirror repo and runs a plain `git pull` will hit a rejected non-fast-forward merge or a confusing divergent-branch error, not a clean update. The correct way to get the latest state of a mirror is to re-clone it (or `git fetch && git reset --hard origin/main`), not pull. This is a real, common gotcha for anyone treating the mirror as a normal git history rather than a snapshot of current state — document this prominently anywhere a mirror repo's README would be read, rather than assuming force-push is "just an implementation detail."

**Scaling note:** `git subtree split` re-walks the full history of each package's prefix on every run, not just the incremental change. This is fine at current repo size and will get slower as `felixs-tools`'s history grows. Not worth solving now — just something to watch, and a signal (not the only one) that the mirror workflow itself may need revisiting someday.

## 6. Tech stack

Python across every package — deliberately one language for one dependency toolchain, one linter config, one CI setup, and because the ML tooling (model serving, fine-tuning, LLM SDKs) is Python-first.

| Package | Key libraries | Storage |
|---|---|---|
| Logger | `drain3` (log templating), `ollama` / `llama-cpp-python` (local model serving), `sentence-transformers` (novelty/embedding scoring), `mcp` (Python MCP server SDK, for its MCP interface) | SQLite + FTS5 |
| Brain | `GitPython` (co-change/ownership graph — the first piece built), `tree-sitter` + language grammars (structural extraction, one language first), `tree-sitter-stack-graphs` or its early Python bindings (call/import resolution — only if naive name-based linking proves insufficient, see Section 3.2), `mcp` (MCP server SDK); `watchdog` only if/when incremental updates are actually built | SQLite (adjacency-list tables + recursive CTEs); consider an embedded graph DB (e.g. Kùzu) only if traversal complexity outgrows SQL |
| Router | `litellm` (SDK mode — backend abstraction and fallback/retry come from this, not hand-written), `diskcache` (exact-match caching) for the thin decision-policy/cache wrapper | `diskcache`'s own store |
| Swarm | Custom lightweight asyncio-based DAG executor to start; evaluate `LangGraph` once presets get complex enough to justify it; `mcp` (MCP client, for calling GitHub/Jira's MCP servers, and MCP server SDK, for exposing presets as tools) | SQLite (per-run checkpoint state) |
| common / cli | `pydantic` (shared schemas/config/types), `typer` (the `flx` CLI) | — |

Fine-tuning (Logger's side project only): LoRA on a small base model (e.g. MiniCPM-1B class) via a framework like Unsloth or Axolotl. One-time effort, not a recurring pipeline.

**Packaging caveat:** Python end-to-end is the fastest path to build and iterate, but it means anyone else installing one of these tools needs a Python environment, not a single binary. If "usable by other solo devs" becomes a real priority later, the CLI boundary is the piece most worth reconsidering — a thin compiled binary (Go/Rust) that talks to a local server, keeping the Python underneath for model/orchestration logic. Not a current-phase concern.

## 7. Build sequencing

1. **`common/` types only.** Task-type taxonomy, Router request/response shape, preset schema, Brain query result shape, and a **shared location/entity identifier** — a canonical way to refer to "this part of the codebase" (file path, optionally mapped to a service/component label) that both Logger and Brain index against. Without this, incident-response and code-review presets have no reliable way to join "Logger's anomaly happened here" with "Brain's blast radius for here" — this gap only shows up once Swarm needs to correlate the two, so it belongs in `common/` from the start rather than being discovered mid-build. No logic beyond this — this is the shared contract everything else is built against, so it needs to exist before any package does.
2. **Logger, standalone.** Build against a stock small model with good prompting first — no fine-tuning yet. Router is a stub (pass-through, no caching/cascading). Use it for real daily log-search tasks before adding anything further.
3. **Brain, standalone, in its own internal order** (Section 3.2): git co-change/ownership graph first, then single-language structural extraction with full-rebuild-per-run, then naive name-based call linking. Reuses the Router stub and storage patterns as a consistency check on whether the `common/` types were actually right.
4. **Router, made real.** Now a thin wrapper around `litellm` rather than a from-scratch package (Section 3.3) — this step is just writing the decision policy and cache once Logger and Brain have generated real call patterns to route between, not designing a backend abstraction.
5. **Swarm, last, deliberately.** Only after weeks of manually running Logger/Brain workflows by hand — e.g. manually stepping through an incident response — so the preset schema reflects real repeated steps rather than a guessed abstraction.
6. **Generalize only on demonstrated need** — incremental Brain updates, import-aware call resolution via stack-graphs, cascading in Router, semantic caching, additional packages and languages — each only once the bare-bones version has measurably started to hurt, per the rule of three.

## 8. Maintenance model

Distinguishing forced upkeep from voluntary growth, since "used forever" makes this worth being precise about:

| Surface | Maintenance reality |
|---|---|
| Logger's fine-tuned model | None — it's frozen by design. Only degrades if the query schema it was trained against changes later, which is a self-inflicted, optional risk |
| Logger's parser/index, Brain's core graph logic, Router's policy/cache, Swarm's executor | Own code — write-once if kept simple, no external forcing function |
| `drain3`, SQLite, tree-sitter grammars | Mechanical dependency bumps, low effort, automatable (e.g. Dependabot) |
| Provider API changes (now inherited via `litellm`) | Still the one real exposed seam to fast external change, but `litellm` absorbs most of the adapter-tracking work upstream rather than this project maintaining hand-written adapters |
| Anomaly scorer (if run continuously) | Operational upkeep, not code rot — it's a process that needs to stay running, a different kind of chore than maintenance |
| Adding presets, language support, new packages | Voluntary growth, not decay — this is the intended way the project expands, not a cost imposed on it |

## 9. Non-goals (explicitly deferred, not rejected)

- Incremental Brain updates — build only if full-rebuild is proven too slow.
- Cascading/confidence-based escalation in Router — useful refinement, not required to start; confidence signals from small models are an imperfect heuristic and shouldn't be over-trusted.
- Semantic caching in Router — exact-match only until proven insufficient.
- Bidirectional repo sync — build only if an outside contributor on a mirror repo actually materializes, and even then, PR-based, never a direct auto-push back.
- Auto-merge or any autonomous external action — this one is a **permanent** non-goal, not deferred. Every side-effecting preset step is human-gated, always.
- API stability guarantees / packaging polish for external users — defer until interfaces have stabilized through the author's own daily use. Building this too early risks locking in the wrong abstractions.
- Speculative extensibility hooks for packages that don't exist yet — add structure when a real second or third use case needs it, not before.
- Multi-language support in Brain — one language first; add more only when actually needed day to day.
- Import-aware call resolution via `tree-sitter-stack-graphs` in Brain — naive name-based linking first; escalate only once its false-positive rate is actually a problem in practice, not preemptively.

## 10. Open items (not yet decided)

- Exact preset config schema: what fields a preset file needs (step list, which service each step calls, how results pass between steps, retry/failure semantics). To be defined from real manual workflows per Section 7, step 5.
- Brain's exact query API surface / query language — not yet finalized.
- Whether `tree-sitter-stack-graphs`'s Python bindings are mature enough to depend on by the time Brain needs proper call resolution, or whether that means using the Rust library directly (or a different approach entirely) — currently work-in-progress and fork-dependent, revisit maturity before committing either way.