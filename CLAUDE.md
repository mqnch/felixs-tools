# CLAUDE.md

Instructions for any AI assistant (or human) working in this repo.

## Current focus

Post-training Logger's **query planner** with execution-verified rewards, as a recruiting artifact ([decision 0001](docs/decisions/0001-post-trained-planner-is-primary-deliverable.md)). Work is sliced in [docs/slices/README.md](docs/slices/README.md), slices 002–012. Brain and Swarm are deferred behind it — don't start work on them without saying so.

Two constraints that are easy to violate by accident:

- **The query DSL freezes at the end of slice 002.** After that, changing it invalidates the dataset *and* every trained checkpoint. Treat a post-freeze DSL change as a retrain, not an edit.
- **Slice 005 is a go/no-go gate.** Measure stock-model baselines before spending GPU time. If a stock model is already near the ceiling, harden the DSL instead of training.

## Read first

1. [docs/sourceoftruth.md](docs/sourceoftruth.md) — canonical brief. Design philosophy, package boundaries, build order, non-goals. **Read this before proposing or building anything.**
2. The README of whichever package you're touching (`packages/*/README.md`, `cli/README.md`) — each has a `Status` section stating what is actually built.
3. [docs/slices/README.md](docs/slices/README.md) — what has shipped so far and what it unlocked.
4. [docs/decisions/README.md](docs/decisions/README.md) — decisions made after the source of truth was written.

## The two rules that govern everything

- **Litmus test** (§2.1): if you deleted the LLM call, would anything be left? If no, it's a Swarm **preset** (config), not a package.
- **Build bare bones, generalize only on demonstrated pain** (§2.2). Not speculatively. Pain goes in [docs/friction.md](docs/friction.md) with a date, or it doesn't count.

If a request conflicts with these, say so before building, then do what the user decides.

## Documentation is part of the work, not a follow-up

A change is not done until the docs below are updated **in the same change**. Do not batch documentation into a separate later pass — the reasoning is only cheap to write down while it's still in your head.

### Definition of done

For any change that ships behavior:

| Trigger | Required doc |
|---|---|
| Any behavior-shipping change | A **slice entry** in `docs/slices/` (new file, or append to the open one) |
| A choice with a real alternative that was rejected | A **decision record** in `docs/decisions/` |
| A package's built-ness changed | Update that package's README `Status` section |
| A new module, env var, or CLI command | Update that package's README table/CLI section |
| Bare-bones version cost real time or gave a wrong answer | A dated line in `docs/friction.md` |
| Build order, scope, or a non-goal actually changed | Edit `docs/sourceoftruth.md` and say so in the slice entry |

`docs/sourceoftruth.md` stays **canonical and current** — it describes the project as it is meant to be, not a historical log. Slices and decisions are the append-only history. When they disagree with the source of truth, the source of truth is wrong and should be edited.

### Slices

A slice is a **thin vertical cut that ends in something usable** — not a task, not a file. "Logger ingests a file and answers one natural-language query end to end" is a slice. "Add index.py" is not.

Write it as you go, not from memory afterward. Template and full rules: [docs/slices/README.md](docs/slices/README.md).

The part that matters most is **what was deliberately left out**. This project is built on deferring things on purpose; a slice that doesn't state its own cut lines reads later as an oversight instead of a decision.

### Decisions

Write a decision record when you picked between real options — adopt vs. build, library A vs. B, an accepted known-wrong shortcut, a schema shape that other packages must build against. Do **not** write one for choices with no live alternative.

Record the rejected option and **why it was rejected**, so it isn't silently re-proposed six months later. Template and rules: [docs/decisions/README.md](docs/decisions/README.md).

Several decisions predate this system and live inline in `docs/sourceoftruth.md`; the decisions index maps them. Don't duplicate them into new records — link to the section.

## Working conventions

- **Python everywhere**, `uv` workspace. `uv sync --all-packages`, `uv run felix ...`, `uv run pytest`.
- Packages depend on `common` for shared shapes. Don't duplicate a type that belongs there; don't put logic in `common`.
- Brain has **no model dependency** — not even optional. Don't wire it to Router.
- Router is a plain library, never an MCP server.
- Side-effecting steps are **human-gated, permanently** (§2.3). No autonomous external action, no auto-merge.
- MCP servers are added **per package on demonstrated need**, not as scaffolding.
- Respect the build order (§7). Don't start Brain work while Logger is unproven in real use; don't design Swarm's preset schema from imagination.

## When asked to build something not in the source of truth

1. Run the litmus test out loud.
2. Check §9 (non-goals) — it may be deliberately deferred, in which case say what evidence would justify un-deferring it.
3. If it's genuinely new scope, build it *and* update `docs/sourceoftruth.md` plus a decision record — an undocumented scope change is the failure mode this file exists to prevent.
