# Friction log

Plain-text notes when a bare-bones piece costs real time or produces a wrong answer.
Date each entry. Do not turn this into a metrics system.

This is the evidence that unlocks anything in source of truth §9 — nothing gets generalized
without lines in here first (§2.2). Design reasoning goes in `decisions/`, not here.

<!-- Example:
2026-08-01: naive linking wired two unrelated parse() functions together, wasted 10 min
-->

2026-08-15: adapters validated against loghub *_2k.log samples passed 100% while being
wrong on the real datasets - BGL's optional <NodeRepeat> silently yielded level="Kill",
Thunderbird dropped spaced program tags. Samples are filtered; Hadoop_2k.log has 0 of the
continuations that are 54% of the real file. Rule going forward: scan the full file for
non-matching lines before trusting any adapter.

2026-08-15: passed skipped_lines=counter.value to the manifest builder before the lazy
parse generator had run, so it always recorded 0. Eagerly reading a counter a generator
fills later is easy to repeat - the parameter now takes a callable.
