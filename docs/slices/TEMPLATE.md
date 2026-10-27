# NNN — <title>

**Date:** YYYY-MM-DD (or `planned`)
**Status:** Planned | In progress | Shipped | Abandoned
**Touches:** `packages/x`, `packages/y`
**Source of truth:** §N.N, §7 step N
**Decisions:** [NNNN-title](../decisions/NNNN-title.md)
**Depends on:** NNN (what must be finished first)

## What a person can now do

One or two sentences, stated as capability, not implementation. Include the command or call if there is one.

```bash
uv run felix ...
```

## How it works

Only the parts a future reader can't get from the code quickly: the shape of the flow, what talks to what, where state lives.

## Deliberately not in this slice

The most important section — write it even if it feels obvious.

- <thing left out> — <why: deferred per §9 / no real need yet / blocked on X>
- <shortcut knowingly taken> — <the known failure mode, and what would trigger fixing it>

## Decisions made here

- [NNNN-title](../decisions/NNNN-title.md) — one-line summary
- (or "none — no live alternatives")

## Friction observed

Anything that cost real time or gave a wrong answer. Also add it to [../friction.md](../friction.md) with a date. "None yet — not used for real work" is a valid answer.

## What this unlocks

The next slice(s) this makes possible, and anything that must be used for real work before moving on.
