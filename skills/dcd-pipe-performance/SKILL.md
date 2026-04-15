---
name: dcd-pipe-performance
description: Design, implement, profile, or review DCD/data-processing pipes for performance, especially Lance/Arrow batch pipelines with large tables, binary columns, dedup, compaction, and reproducible optimization experiments.
---
# DCD Pipe Performance

## Purpose

Use this skill when building or optimizing a pipe that reads, transforms, deduplicates,
or writes large datasets.  It is especially useful for Lance/Arrow-based pipes and
pipelines with image/audio/video bytes, long text, embeddings, JSON metadata, or other
wide columns.

The goal is to keep pipe code fast, measurable, reproducible, and semantically safe.

## Core Principles

### 1. Profile first

Before optimizing, add timing around:

- input scans
- parsing / transform CPU
- joins, grouping, and dedup
- wide-column reads
- output writes
- sidecar file finalization
- compaction and index creation

Separate stage timing from hotspot timing.  A good profile should make it obvious
whether the bottleneck is CPU, Python object conversion, repeated commits, binary I/O,
or compaction.

### 2. Prefer single-commit writes

Avoid writing a Lance dataset with many loop-level append commits when the output can be
streamed as batches.

Preferred pattern:

- transform input into Arrow `RecordBatch` / `Table` chunks
- stream chunks through a writer abstraction
- when possible, use a generator/iterator that yields `RecordBatch` objects, wrap it
  with `pa.RecordBatchReader.from_batches(schema, batches)`, then pass the reader to
  Lance
- call `lance.write_dataset(..., mode="create")` once per output table

Benefits:

- fewer commits
- fewer fragments
- less manifest churn
- lower downstream compaction pressure
- simpler performance profile

Keep the older append strategy available only when needed for compatibility or very
specific memory constraints.

### 3. Scan narrow columns before wide columns

For dedup, filtering, and routing, first scan only the columns needed to decide which
rows survive.  Usually these are narrow columns such as:

- `id`
- `sha256`
- timestamps
- partition keys
- row positions

Only after selecting kept rows should the pipe read wide columns such as:

- image bytes
- audio/video bytes
- embeddings
- large text blobs
- large JSON payloads

For Lance, a common pattern is:

1. scan narrow columns
2. compute first/kept row ids
3. use `Dataset.take(row_ids)` to read only kept wide rows
4. stream-write the output

### 4. Use Polars selectively

Polars is useful for narrow-column helper work:

- grouping ids
- computing first row per key
- checking uniqueness
- comparing id sets
- building dedup helper tables

Do not assume Polars should own every path.  Keep complex plugin logic, HTML rewrite,
custom JSON merge semantics, and sidecar generation in straightforward Python unless
there is clear evidence that vectorization helps.

### 5. Avoid unnecessary Python row objects

For large Arrow batches, avoid defaulting to `batch.to_pylist()` for the whole row when
only a few fields are needed.

Prefer:

- column access
- typed arrays
- lightweight tuples
- batch-level builders

Use row dicts when the logic is small or clarity matters more than conversion overhead.
Validate with profiling before complicating code.

### 6. Treat compaction as a maintenance step, not just overhead

Compaction and index creation can make later pipeline stages faster and cleaner.  Do not
remove them just to make the current pipe look faster unless the user explicitly wants a
maintenance-policy experiment.

For large binary tables, be careful:

- logical delete can be fast
- materializing deletes during compaction can rewrite all kept bytes
- compacting a small metadata table may be cheap and valuable
- compacting a huge image table may dominate runtime

If downstream access is mostly key lookup into a binary table, consider testing:

- compact metadata tables
- create an id index on the binary table
- leave binary-table deletion masks unmaterialized

Always label this as a policy/storage-layout variant unless it exactly matches the
existing maintenance behavior.

### 7. Make semantic checks mandatory

Every performance run needs logical equivalence checks unless the run intentionally
changes semantics.

Compare logical content, not physical layout:

- row count
- selected columns
- normalized JSON where appropriate
- sidecar row count and hash
- stable fingerprints

Do not compare Lance file names, fragments, manifests, or physical version layout as
correctness criteria unless the task is explicitly about storage layout.

### 8. Use explicit strategy objects for experiments

Avoid scattering experimental flags through business logic.

Prefer a small strategy/config object with fields such as:

- `write_strategy`
- `dedup_engine`
- `row_mode`
- `compact_policy`
- `passthrough_policy`
- `parallelism`
- `report_tags`

Each run should record its strategy in a manifest or profile JSON.

### 9. Preserve reproducible runs

For serious optimization work, each run should keep:

- code snapshot
- output dataset
- timing profile
- logs
- manifest with input, CLI args, strategy, and summary metrics
- equivalence report

Generate a compare report that shows:

- total runtime
- speedup vs baseline
- stage deltas
- hotspot deltas
- semantic-equivalence status
- paths to code, output, reports, and logs

## Recommended Workflow

1. Establish a baseline run and profile.
2. Identify top hotspots before changing code.
3. Try one optimization at a time.
4. Keep each experiment reproducible.
5. Validate logical equivalence.
6. Compare stage and hotspot deltas.
7. Combine only the optimizations that independently helped.
8. Separate semantic-equivalent runs from policy or dependency variants.
9. Promote only the simplest strategy that gives reliable speedup.

## Optimization Checklist

When reviewing or building a pipe, check:

- Are we repeatedly appending/committing an output table?
- Can output writes be changed to one stream-once commit?
- Are we scanning wide columns before we know which rows survive?
- Can dedup/filtering be done from narrow columns first?
- Are we converting whole batches to Python rows unnecessarily?
- Is Polars useful for just the narrow helper computation?
- Are compaction and index costs measured separately?
- Are we accidentally rewriting large binary columns during compaction?
- Are semantic checks comparing logical content instead of physical layout?
- Are experiments recorded with code/output/report/log snapshots?

## When To Be Skeptical

Be cautious with:

- multiprocessing for small datasets or I/O-bound paths
- delete-plus-compact on huge binary tables
- global dependency rewrites without a clear hotspot
- skipping compaction without understanding downstream cost
- optimizations that depend on stronger business assumptions than the original pipe

If an optimization changes semantics, name that explicitly in the report and keep it out
of the default recommendation unless the user confirms the new semantics are intended.
