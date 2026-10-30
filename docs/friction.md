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

2026-10-30: first real gen-data run (HDFS, 200k-row sample, --n 20000 --dry-run) stalled
for 25 min at 3.5k train examples, almost all aggregate/time_range. Cause: HDFS has ~29
templates, so nearly every row-returning plan on a 160k-row train split matches >= MAX_LIMIT
(1000) rows and is rejected as truncated_rows (decision 0013). Re-ingesting at 20k rows
still rejected 8355/9600 train attempts as truncated_rows and gave up at 166/240. Slice
004's "MAX_LIMIT binds long before the breadth cap" note was right and bit on day one.

2026-10-30: staging.ARCHIVES pointed OpenStack, Spark and Thunderbird at .zip files that
404 on Zenodo record 8196385; the real files are .tar.gz. Never exercised because staging
downloads are opt-in and untested against the network. Fixed the three URLs.

2026-10-30: BGL dry run crashed building SeverityNode("SEVERE"). Slice 003 kept BGL's
SEVERE/FAILURE on purpose; slice 002 froze an enum without them; nothing checked one
against the other, and ingest stored the values without complaint. Fixed by decision 0015.
