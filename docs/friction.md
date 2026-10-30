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

2026-10-30: first paid pilot (Haiku 5.5 via OpenRouter, prompt q-2026-10-27.1, 870
questions, $0.23): 607 said "up to 1000", 776 said "newest"/"most recent", 620 opened
"Show me". The sampler's limit=MAX_LIMIT/order=newest defaults were shown to the author
alongside "express every constraint". Prompt q-2026-10-30.1 hides default limit/order from
the author's view of the plan and asks for varied phrasing: 19 / 0 / 51 on the rerun, and
the 19 are log content ("soft limit", "maxEvents 10000"), not the result limit.

2026-10-30: audit of pilot 2 (q-2026-10-30.1; 102 rows, Claude first pass, not a human)
failed decision 0004's trigger: answerable 75% (Hadoop 62%, BGL 82%, OpenStack 79%).
Causes, most to least common: the author describes sample lines as if they were filters
("about spills"); names a whole file for a one-component location_key; says "last N hours"
for absolute windows; truncates IDs; asks "how many" of row queries. Sampler side: AND
leaves implied by a sibling template (term=state AND "wait state enable") and stopword
terms (term=such). Fixed with prompt q-2026-10-30.2 (location/window rendering, shape and
sample rules), a noop_conjunct gold rejection, and a term stoplist.

2026-10-30: CorpusView.template_text used MIN(template) per template_id. Logger stores each
row's template as Drain had it at ingest, and Drain only generalizes, so early rows keep the
literal text ("1534 double-hummer alignment exceptions") and MIN picks it ('1' < '<'). The
author was shown fully literal patterns for ~1/3 of templates and wrote over-specific
questions ("kvstart = 26214396; length = 6553600"); sampler term leaves came from the same
stale per-row text. Now uses the last-ingested row's template. Logger's index still stores
stale per-row templates; anything else reading log_entries.template has the same trap.

2026-10-30: under q-2026-10-30.2 the author was still shown aggregate group keys
("KERNEL -> 56"), and in 6 of 34 BGL audit rows it turned them into filters ("how many
KERNEL lines..."), despite an explicit rule against exactly that. Prompt rules lost to
visible data twice today (limit/order, then group keys); hiding the data fixed both.
