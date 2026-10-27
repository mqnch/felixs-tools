# 003 — LogHub corpus ingestion

**Date:** 2026-08-15
**Status:** Shipped
**Touches:** `packages/logger` (new `logger.corpora` subpackage only)
**Source of truth:** §3.1
**Decisions:** [0004](../decisions/0004-reverse-generated-gold-over-loghub.md)

## What a person can now do

Build a reproducible, indexed, licence-audited corpus from any of the six LogHub
datasets, and verify on a rerun that they got the same corpus back.

```python
from logger.corpora import ingest_loghub

manifest = ingest_loghub(
    "hdfs",
    source="corpora/raw/hdfs/extracted/HDFS.log",
    out="corpora/hdfs.db",
    sample_size=200_000,
)
manifest.content_digest  # same command + same seed -> same digest
```

**The CLI is deliberately not wired** (see the cut lines). The intended surface,
for whoever wires it:

```bash
felix logger ingest-corpus loghub --dataset hdfs --sample 200000 --out corpora/hdfs.db
```

| Flag | Maps to | Notes |
|---|---|---|
| `--dataset` | `ingest_loghub(dataset)` | one of `bgl hadoop hdfs openstack spark thunderbird`; `registry.dataset_names()` is the enum source |
| `--sample` | `sample_size` | omit for a full ingest |
| `--out` | `out` | manifest lands beside it as `<name>.manifest.json` |
| `--seed` | `seed` | defaults to `DEFAULT_SEED = 20260815`, never to system entropy |
| `--source` | `source` | staged file or directory; `staging.stage_dataset` produces it |
| `--require-publishable` | `require_publishable` | refuses a dataset whose licence does not clear derived-data publication |

## How it works

Five pieces, all under `logger/corpora/`, all new files:

- **`base`** — `DatasetAdapter` (pure, stateless, no I/O) maps a raw line to a
  `CorpusRecord`: message body, ISO timestamp, severity, `LocationId`, anomaly
  label, and a dataset-specific `extra` dict.
- **`loghub`** — the six adapters, one regex each, following loghub's own
  `log_format` templates so rows line up with the published `*_structured.csv`.
- **`sampling`** — seeded reservoir sampling (Algorithm R): one pass, O(k)
  memory, no need to know the line count in advance, result re-sorted into
  source order. Plus `ContentDigest`, a SHA-256 over the ordered row content.
- **`manifest`** — `CorpusManifest` dataclass + JSON, written both as a sidecar
  file and into a `corpus_manifest` table inside the corpus database.
- **`ingest`** / **`staging`** — the build entrypoint, and the
  download/unpack path (opt-in, never executed in tests).

**Where the label goes.** `index.py` is owned by slice 002 and was not touched.
The anomaly label and the `extra` fields therefore live in a **sidecar table**,
`corpus_records(entry_id, dataset, source_index, label, extra)`, in the same
SQLite file. Nothing reads `label` — see the cut lines.

**Reproducibility is checkable, not merely claimed.** A corpus database is *not*
byte-identical across runs: both the manifest and `log_entries.ingested_at`
record wall-clock time. So the manifest carries a `content_digest` over the
ordered `(raw, timestamp, severity, location_key, label)` tuples, and
`CorpusManifest.reproduces()` compares everything except the clock. Verified
end-to-end against all six real 2k samples: identical digests, identical
template counts.

## Per-dataset findings

Every format below was verified by parsing that dataset's real `*_2k.log` sample
from the loghub repo — **100% of lines matched, 0 skipped, for all six** — and
cross-checked against a full-dataset scan of HDFS, BGL, OpenStack, Spark and
Hadoop. **That cross-check mattered: see the trap section below.**

| Dataset | Format | Timestamp → ISO | Severity vocabulary | `LocationId.service` | Size |
|---|---|---|---|---|---|
| **HDFS_v1** | `<Date> <Time> <Pid> <Level> <Component>: <Content>` | `081109 203615` (YYMMDD HHMMSS, no year century, no TZ) → `2008-11-09T20:36:15` | `INFO`, `WARN` | Java class, e.g. `dfs.DataNode$PacketResponder` | 1.47 GiB / 11,175,629 lines |
| **BGL** | `<Label> <Timestamp> <Date> <Node> <Time> <NodeRepeat> <Type> <Component> <Level> <Content>` | `2005-06-03-15.42.50.675872` → `2005-06-03T15:42:50.675872`; epoch column kept in `extra` | `INFO`, `WARN`, `ERROR`, `SEVERE`, `FATAL`, `FAILURE` | `Component`: `KERNEL`, `APP`, `MMCS`, `DISCOVERY`, `HARDWARE`, … | 708.76 MiB / 4,747,963 lines |
| **Thunderbird** | `<Label> <Id> <Date> <Admin> <Month> <Day> <Time> <AdminAddr> <Content>` | `2005.11.09` + `Nov 9 12:01:01` → `2005-11-09T12:01:01`; year from the `<Date>` column, never guessed | **NONE — no level field exists** | derived from the syslog process tag (`crond(pam_unix)[2915]:` → `crond`) | 29.60 GiB / 211,212,192 lines |
| **OpenStack** | `<Logrecord> <Date> <Time> <Pid> <Level> <Component> [<ADDR>] <Content>` | `2017-05-16 00:00:00.008` → `2017-05-16T00:00:00.008000` | `INFO`, `WARNING`→`WARN`, `ERROR`, `CRITICAL` | `Component`, e.g. `nova.osapi_compute.wsgi.server`; `path` is the rotated log file (`nova-api.log`) | 58.61 MiB / 207,820 lines |
| **Spark** | `<Date> <Time> <Level> <Component>: <Content>` | `17/06/09 20:10:40` → `2017-06-09T20:10:40` | `INFO`, `WARN`, `ERROR` | `executor.CoarseGrainedExecutorBackend`, … | 2.75 GiB / 33,236,604 lines |
| **Hadoop** | `<Date> <Time> <Level> [<Process>] <Component>: <Content>` | `2015-10-18 18:01:47,978` → `2015-10-18T18:01:47.978000` | `INFO`, `WARN`, `ERROR`, `FATAL` | `org.apache.hadoop.…MRAppMaster`; `path` is the per-container file | 48.61 MiB / 394,308 lines |

**Anomaly labels — four different mechanisms, and only two are inline.** A bare
"has labels" boolean would be actively misleading, so each adapter carries a
`label_source` string instead. `CorpusRecord.label` is populated only for the
inline cases; the rest need a join whose key is preserved in `extra`.

| Dataset | Where the label lives | Join key | Preserved as |
|---|---|---|---|
| BGL | **inline**, field 1: `-` or one of **41** alert tags (348,460 of 4,747,963 lines) | — | `corpus_records.label` |
| Thunderbird | **inline**, field 1: `-` or an alert tag (`VAPI`, `ECC`, `SCSI`, `MPT`, …) | — | `corpus_records.label` |
| HDFS | `preprocessed/anomaly_label.csv` — 575,061 block traces, 16,838 anomalous (2.93%) | BlockId | `extra.block_id` |
| OpenStack | `anomaly_labels.txt` — 4 VM instance UUIDs, plus a normal/abnormal file split | instance UUID | `extra.instance_id` |
| Hadoop | `abnormal_label.txt` — per **application directory**: Normal / Machine down / Network disconnection / Disk full | application id | the file path, via `for_file` |
| Spark | **none at all** — loghub ships it as-is, mixing normal and abnormal runs | — | — |

None of these joins is implemented — slice 003 builds no scorer. Only the keys
are extracted, so a future scorer slice does not force a re-ingest.

## The sample-vs-full trap

The `*_2k.log` samples are **not representative**, and validating only against
them is how this slice nearly shipped two silent bugs. Both were caught by a
full-dataset cross-check and are now regression-tested with verbatim fixtures:

- **BGL: 316 real lines omit `<NodeRepeat>` entirely** (they also carry
  `Node="-"`). Positional splitting shifts every later field right, silently
  producing `component="FATAL"` and `level="Kill"`. My adapter did exactly this
  before the fix. The regex now anchors `<Type>` to its closed vocabulary
  (`RAS|NULL`) so it backtracks into the 9-field form. **No such line exists in
  `BGL_2k.log`.**
- **Thunderbird program tags can contain spaces** (`Server Administrator:`) and
  **255 of 2000 sample lines have no `[PID]`**. The first pattern dropped the
  service entirely; service extraction on the sample is now 2000/2000.

Three more traps, handled and tested but worth stating because they change what
a corpus *is*:

- **`Spark_2k.log` is 100% `INFO`** and **`Thunderbird_2k.log` is 100% `-`**. Neither
  sample contains a single example of its own WARN/ERROR or alert-tag vocabulary.
- **Continuation lines are the majority case for Hadoop.** 54.1% of the real
  Hadoop dataset and 17.5% of Spark are Java stack-trace continuations
  (`\tat org.apache...`, `Caused by:`, `... 14 more`). **`Hadoop_2k.log` contains
  zero of them** — they were filtered when the sample was cut. They are correctly
  skipped and counted in `manifest.skipped_lines`, but expect a real Hadoop
  ingest to report a ~54% skip rate. That is not a bug; a `--sample N` still
  yields N usable rows, because sampling happens post-parse.
- **OpenStack has 184 traceback lines that repeat the full prefix but omit the
  `[<ADDR>]` group.** The bracket group is optional, so these parse.

**Timezones, since both supercomputer logs carry two clocks.** BGL's epoch column
read as UTC runs +7h/+8h ahead of its printed time (US Pacific with DST — LLNL is
in Livermore, CA). Thunderbird's is a constant +8h, even though Sandia is in
Albuquerque (MST, UTC−7) — consistent but unexplained, which is one more reason
not to treat the epoch as authoritative. Both epochs are preserved in `extra`.

## Licensing — the gate on publishing derived data

Verified 2026-08-15 against primary sources. Also encoded in
`logger/corpora/licenses.py` so `require_publishable=True` can actually refuse a
dataset, rather than depending on someone remembering this table.

**The headline problem: loghub ships two licences that contradict each other.**
The repo `LICENSE` is a bespoke text — "freely available for **research or
academic work**" plus a citation requirement — which GitHub's detector cannot
match to any known licence (`spdx_id: NOASSERTION`). Every Zenodo record that
actually hosts the data declares **CC BY 4.0**, which permits commercial use and
derivatives. No loghub statement says which wins. This is unresolved and is
*not* smoothed over anywhere in the code.

| Dataset | Upstream licence | Derived data publishable? | The catch |
|---|---|---|---|
| **HDFS_v1** | **BSD** (Wei Xu's SOSP'09 page, explicit) | Yes, with attribution | Cleanest of the six. Permissive independent of the loghub conflict, and explicitly benchmark-generated so no privacy review is needed. |
| **BGL** | **None stated** (USENIX CFDR / HPC4) | Yes, with attribution — but see catch | **Weakest link.** No licence, no terms, no research-only clause — but also *no affirmative grant*. Absence of a restriction is not permission. Ungated public download, cleared for public release, universally redistributed in the literature. |
| **Thunderbird** | **None stated** (USENIX CFDR / HPC4) | Yes, with attribution — but see catch | Same gap as BGL, plus this is real production syslog: usernames, hostnames and IPs in message bodies. |
| **OpenStack** | loghub terms; upstream DeepLog (CCS'17), no separate licence | Yes, with attribution | Not LogPAI-collected — originates with the DeepLog authors. |
| **Spark** | loghub terms only | Yes, with attribution | LogPAI's own CUHK lab data. No third-party layer. |
| **Hadoop** | loghub terms; upstream ICSE'16 (MSR), no separate licence | Yes, with attribution | Requires the ICSE'16 citation on top of loghub's. |

**No NC, no ND, and no research-use-only clause exists anywhere in the chain.**
Publishing this corpus as *research output* is permitted under either reading of
the loghub conflict, which is why all six are marked
`PUBLISHABLE_WITH_ATTRIBUTION`. **Commercial redistribution is not cleared** and
rests on the CC BY reading alone.

Two things that materially reduce the remaining risk, neither done yet:

1. **Email the loghub maintainers.** Issue #5 asks almost exactly this question
   ("redistribution rights of derivatives"); maintainer zhujiem answered within
   hours that redistributing derivatives is fine with a link back for credit —
   but scoped his answer to the *2k sample* logs, and a GitHub comment is not a
   licence amendment. One email converts the only material ambiguity into a
   documented permission.
2. **Privacy-review the sampled rows.** loghub states the logs are **NOT**
   sanitized, anonymized or modified. That applies to BGL, Thunderbird,
   OpenStack and Hadoop regardless of licence.

`licenses.PUBLICATION_CHECKLIST` carries the attribution obligations (ship the
loghub LICENSE verbatim, link the repo, cite the ISSRE'23 paper plus every
per-dataset paper, state that the corpus was sampled/parsed/re-indexed since CC
BY requires indicating changes, acknowledge Stearley and Oliner for CFDR, retain
the BSD notice for HDFS).

## Decisions made here

Real choices with rejected alternatives. **No decision record file was created —
numbering would collide with concurrent work; assign a number and lift these out
if any deserves one.**

- **Reservoir sampling over head-N truncation.** Head-N is trivially
  deterministic, but every sampled row would come from one contiguous time
  window — which destroys the time-based train/test split decision 0004 requires
  for contamination control. Hash-modulo sampling was also rejected: it yields
  only an approximate sample size, and Python's builtin `hash()` is salted per
  process, so the obvious implementation is silently non-reproducible.
- **Sample in source order, not selection order.** Costs a sort of k items;
  buys chronologically ordered corpora and — because drain3's template ids are
  assignment-order-dependent — reproducible template ids.
- **`raw` is the message body, not the whole line.** Templating the full line
  would make drain3 cluster on timestamps and pids, and FTS terms would match
  against pid digits. Every stripped field is captured structurally, so this is a
  split, not a loss. The cost: the original line is not stored byte-for-byte and
  is only reconstructable up to whitespace.
- **No timezone is invented.** None of the six datasets records a UTC offset, so
  adapters emit naive ISO-8601 rather than stamping `+00:00`. The index layer
  applies its own documented "naive means UTC" rule on top; both are
  deterministic, and the corpus digest is taken pre-normalisation so it is stable
  against index changes.
- **BGL/Thunderbird use the formatted stamp, not the epoch column.** The epoch is
  the same instant expressed in UTC while the formatted column is site-local;
  picking the epoch would put two datasets on a different clock convention from
  the four that ship local time only. The epoch is preserved in `extra`.
- **Thunderbird gets no severity rather than a guessed one.** It has no level
  field. Regex-guessing a level from message text would invent structure the
  source does not have — and since slice 004's gold answers come from *executing*
  the plan, an invented severity becomes invented ground truth.
- **Labels in a sidecar table, not new `log_entries` columns.** Slice 002 owns
  `index.py` concurrently; a sidecar keeps the label without touching it.

## Deliberately not in this slice

- **No CLI command.** `cli/` is owned by concurrent work, so wiring
  `ingest-corpus` would collide. The entrypoint and its full flag mapping are
  above; wiring should be a Typer signature and nothing else.
- **No `packages/logger/README.md` and no `docs/friction.md` update.** Both files
  were confirmed mid-edit by concurrent slice-002 work while this slice was being
  written, so touching either would have clobbered it. *These are the two
  definition-of-done items consciously left open:* the README needs a
  `logger.corpora` module row plus a `Status` note, and friction.md needs the
  dated sample-vs-full line recorded below.
- **Nothing downloaded, and no dataset ingested for real.** `staging.py` provides
  the fetch/unpack path but downloading is opt-in and was never executed. Slice
  003's open question — whether WATcloud compute nodes have outbound internet —
  is still unresolved, which is exactly why staging is idempotent and works from
  a pre-staged directory with no network.
- **No archive checksums pinned.** `stage_dataset` accepts and verifies an
  `expected_sha256`, but no known-good digests are recorded, because that would
  mean downloading 35 GB to compute them. Until they are pinned, a corpus is only
  as trustworthy as the Zenodo transfer that produced it.
- **No anomaly labels consumed** (decision 0002). Preserved, never read. **None
  of the four label joins is implemented** — only the keys are extracted
  (`block_id`, `instance_id`, the Hadoop application path). Thunderbird's full
  alert-tag vocabulary is also unverified: only ~16% of the 29.6 GiB file has
  been scanned, so treat the known tag list as a lower bound.
- **No cross-dataset schema unification.** Each corpus is its own database, per
  the original scope, so the domain-transfer split in slice 004 stays clean.
- **Node/host is not part of `LocationId`.** BGL's `R02-M1-N0-C:J12-U11` and
  Thunderbird's node are high-cardinality and physically meaningful, but
  `LocationId.path` means "repo-relative file path" and a node id is not one.
  They live in `extra` instead. If slice 004 finds `service` too low-cardinality
  to generate interesting plans, promoting node is the obvious next move.
- **No stratification.** Sampling is uniform over lines, so rare severities and
  rare templates are sampled proportionally — i.e. barely. Decision 0004 requires
  stratification *across DSL features*, which is slice 004's job on the generated
  plans, not this slice's on the rows. If 004 finds it cannot hit rare templates,
  the fix belongs here.

## Friction observed

- **Validating a parser against a curated sample is not validating it.** Two
  adapters were wrong on the real datasets while passing 100% against the
  `*_2k.log` samples — BGL's missing `<NodeRepeat>` and Thunderbird's spaced
  program tag. The samples are filtered in ways nothing documents: `Hadoop_2k.log`
  has zero of the continuation lines that make up 54% of the real file. **The
  general lesson: for any future dataset adapter, scan the full file for lines
  that fail the format before trusting a sample.** Cheap to do, and it is the only
  reason this slice does not ship a corpus with `level="Kill"` in it.
- **The bug the tests caught, worth remembering:** `skipped_lines=counter.value`
  was passed to the manifest builder while the parse generator had not run yet,
  so it always recorded 0. Eagerly reading a counter that a lazy generator fills
  is an easy mistake to repeat; the parameter now accepts a callable.
**Not yet written to `docs/friction.md`** (file was mid-edit by concurrent work).
The line to add:

```
2026-08-15: adapters validated against loghub *_2k.log samples passed 100% while
being wrong on the real datasets - BGL's optional <NodeRepeat> silently yielded
level="Kill", Thunderbird dropped spaced program tags. Samples are filtered;
Hadoop_2k.log has 0 of the continuations that are 54% of the real file.
```

## What this unlocks

- **Slice 004** can sample plans against a real indexed corpus with a citable,
  reproducible provenance record.
- **Before publishing anything derived:** send the loghub maintainers the
  licensing question above, and privacy-review sampled rows from BGL,
  Thunderbird, OpenStack and Hadoop.
- **Before a real corpus build:** wire the CLI, pin archive checksums, and answer
  the WATcloud egress question.
