# akamas-study-analyzer

A Claude Code plugin that deeply analyzes a **finished (or in-progress) Akamas study's
exported results** — every experiment, every parameter combination, and every metric's
full timeseries, not just the goal score — and turns that into an HTML findings report
plus a README recap. It is grounded in the actual exported data and the study's own
`README.md`, not guesswork.

It ships one skill, invoked as `/akamas-study-analyzer:analyze`, that reads a study
folder's config + `README.md` together with an `akamas export study` bundle under its
`results/` folder.

This plugin never touches the **optimization pack** or the **study's own definition**
(goal, parameters, workflow). It only reads them for context. If you need to create or
modify a pack, use `akamas-optimization-pack`; if you need to create or modify a study,
use `akamas-study-manager`.

## What it does

The `analyze` skill:

- Extracts the `akamas export study` bundle (a gzipped tar archive, whatever its file
  extension) into a scratch directory.
- Runs a bundled, dependency-free Python script (`skills/analyze/scripts/analyze_export.py`)
  that computes, straight from the raw export:
  - A per-experiment table (parameters, goal score, failed/succeeded, gain vs. baseline).
  - Per-parameter effects on **every metric in `metricsSelection`**, not just the goal —
    surfacing side effects (e.g. a throughput win that costs memory headroom or raises
    a latency percentile) that a "top experiment" summary alone would miss.
  - Pairwise parameter interactions.
  - Failure and constraint-violation analysis, including a validation pass confirming
    no experiment's parameters actually violated one of the study's own
    `parameterConstraints`.
  - Timeseries aggregates for every metric, plus ready-to-embed chart markup for a
    curated set of the most relevant ones (goal metrics, latency, GPU/memory
    utilization, queueing, throttling) — instability within a trial that a single
    scalar average would hide is called out explicitly.
- Cross-reads the study's own `README.md` so known incidents/hypotheses/pinned-parameter
  rationale already narrated there aren't "rediscovered" as if new — only genuinely new
  findings are flagged as new.
- Writes a single, self-contained HTML report to `results/report.html` (no external
  CDN/network dependency — opens standalone from disk), styled per the `dataviz`
  skill's palette and accessibility guidance.
- Updates the study's `README.md` `## Results`/`## Conclusions` sections (if present,
  as placeholders left by `akamas-study-manager`) and `results/README.md` with a concise
  findings recap linking to the full report — without touching anything else in either
  file.

## What it does NOT do

- It never calls the `akamas` CLI — it only reads an already-exported bundle. If no
  bundle is found under a study's `results/` folder, it tells you to run
  `akamas export study "<Study Name>" <path>` first.
- It never authors or edits the study's own definition (goal, `parametersSelection`,
  `parameterConstraints`, workflow) or the optimization pack — see the sibling plugins
  for those.

## Install

```
/plugin marketplace add <org>/akamas-claude-plugins
/plugin install akamas-study-analyzer
```

## Test locally without installing

From inside a study folder that has a `README.md` and a `results/` folder containing an
exported bundle:

```
claude --plugin-dir /path/to/akamas-claude-plugins/plugins/akamas-study-analyzer
/akamas-study-analyzer:analyze
```

## Usage example

```
$ cd my-vllm-throughput-study/   # has README.md + results/export.gz
$ claude
> /akamas-study-analyzer:analyze
```

The skill extracts `results/export.gz`, runs the bundled analysis script, reads the
study's `README.md` for context, writes `results/report.html` with the full
experiment/parameter/timeseries deep-dive, and updates `README.md`'s `## Results`/
`## Conclusions` sections and `results/README.md` with a recap linking to the report.
