---
name: analyze
description: Deeply analyze a finished (or in-progress) Akamas study's exported results against its config and README, and produce an HTML findings report plus README updates. Trigger on explicit invocation via /akamas-study-analyzer:analyze, and also on natural-language requests such as "analyze this study", "analyze the results in results/export.gz", "generate a findings report for this study", "what did we learn from this study", or "summarize the study results in the README".
---

You are helping an engineer deeply analyze the results of a finished Akamas study —
not just "which experiment scored best," but every interesting side effect, parameter
combination, and metric implication the raw data actually supports, timeseries
included. Follow the steps below in order every time this skill runs.

## 1. Locate the inputs

A study folder for this skill's purposes contains:

- The study's config files (the study/system/component/telemetry/workflow YAML — same
  layout the `akamas-study-manager` plugin creates; see its
  `reference/study-schema.md` for the directory layout if you need to double check).
- A `README.md` describing the study's goal, stack, pinned parameters,
  `parameterConstraints` rationale, and any incidents/manual verification already
  narrated during the study's design and run.
- A `results/` folder containing an exported study bundle — an `akamas export study
  "<Study Name>"` output, a gzipped tar archive (commonly named `export.gz` or
  `export.tar.gz`; the extension is not reliable, `file`/`tar -tzf` is).

If the user names a folder, use it. If not, look for a directory containing both a
`README.md` and a `results/` subfolder with something that looks like an export bundle
in the current working directory or one the user points at. If no export bundle can be
found, tell the user to run `akamas export study "<Study Name>" <path>` and place the
result under that study's `results/` folder before proceeding — this skill never calls
the `akamas` CLI itself (no assumed live session, consistent with the sibling plugins).

## 2. Load the bundled reference material first

Before doing anything else, read `reference/export-schema.md` in this skill's own
`reference/` directory — it documents, file by file, the undocumented internal format
of an `akamas export study` bundle (empirically reverse-engineered, not from
`docs.akamas.io`, which only mentions the command exists). Pay particular attention to:

- The **experiment numbering gotcha**: `last-optimization.json`'s parallel arrays are
  0-based by array position (index `i` = experiment `i + 1`); every other per-experiment
  reference in the bundle (`metrics-*.json`, `logs.json`) already uses the 1-based
  experiment number directly. Getting this backwards silently shifts every
  cross-reference between the per-experiment table and the raw timeseries by one
  experiment.
- `study.kpis[]` vs `study.bestExperiment`: the study-wide best experiment (the goal
  formula's own winner) is usually **not** the same experiment as each individual KPI's
  own best — that divergence between "best for the stated goal" and "best for each
  metric individually" is exactly the trade-off signal this analysis exists to surface.
- `logs.json` contains Akamas **platform** logs only, never the workflow task's own
  stdout (no `kubectl logs`/load-test output) — don't attribute a root cause to this
  file that it can't actually show.
- Raw `metrics-*.json` timeseries span the **entire trial task window**, not the
  windowed/trimmed range the study's own goal score used — a naive full-series mean
  will differ slightly from `last-optimization.json`'s `scores[i]`. The bundled script
  (§3) cross-checks this and flags the gap rather than silently presenting an
  unverified number as exact.

## 3. Extract the export and run the bundled analysis script

1. Extract the export bundle to a scratch directory (never into the study's own repo
   folder — it's raw export data, not a deliverable):
   ```bash
   mkdir -p <scratch-dir>/export && tar -xzf <study-folder>/results/<export-file> -C <scratch-dir>/export
   ```
2. Run `scripts/analyze_export.py` (bundled with this skill, pure Python 3 standard
   library — no install step) against the extracted directory:
   ```bash
   python3 <this-skill's-scripts-dir>/analyze_export.py <scratch-dir>/export --out <scratch-dir>/analysis.json
   ```
   This performs the actual numeric/statistical work — every calculation in the final
   report must trace back to a number this script computed (or a value read directly
   from `study.json`/the README), never an eyeballed or invented figure. It computes,
   and writes into `analysis.json`:
   - A per-experiment table: parameter assignments, goal score, failed/succeeded,
     `parameterConstraints` cross-check (see below), gain vs. baseline.
   - Per-parameter effect breakdown: for every tuned parameter, grouped by value/bucket,
     the mean of the **goal metric and every other metric in `metricsSelection`** — not
     just the goal/KPI metrics — so a parameter's side effects on memory, latency,
     temperature, throttling, etc. show up even when they don't move the goal.
   - Pairwise interaction scans between tuned categorical/low-cardinality parameters
     (e.g. does the best value of parameter A depend on parameter B's value?).
   - Failure and `metricConstraintsViolations` analysis, plus a validation pass
     confirming no experiment's actual parameter assignment violates one of the study's
     own `parameterConstraints` formulas (it should never happen if constraints did
     their job — if it did, that's a significant finding to surface, not to hide).
   - Timeseries aggregates (mean/min/max/stddev) for every metric, per experiment, plus
     ready-to-embed SVG line-chart markup for a curated set of "interesting" metrics
     (goal metrics, latency percentiles, GPU/memory utilization, queueing/preemption,
     container throttling — the script lists exactly which metrics it curated and which
     it left as aggregate-only, so nothing is silently dropped from consideration).
3. If the script errors on an unfamiliar bundle shape (a field this reference doesn't
   cover — see its "Known gaps" section), don't guess: read the raw JSON directly to
   understand the actual shape, fix your understanding, and update
   `reference/export-schema.md` with what you learned, the same way the sibling plugins
   keep their bundled references current.

## 4. Cross-read the README and config — this is not optional

The raw numbers only tell you *what* happened; the README tells you *why* the study was
shaped the way it is, and often already explains an anomaly the data alone would make
you "discover" as if new. Before writing any finding:

- Read the study's `README.md` in full — goal rationale, which parameters are pinned
  and why, every incident already narrated (crashes, manual verification runs), and
  every `parameterConstraints` entry's stated rationale.
- Cross-reference every anomaly `analysis.json` surfaces (a failed experiment, a
  surprising parameter effect, a constraint violation) against the README first. If
  the README already explains it, say so and cite it — don't re-narrate a known incident
  as a fresh discovery. If `analysis.json` shows something the README does **not**
  already cover (e.g. a failure with a root cause the README's incident log doesn't
  mention, or a side effect on a metric nobody discussed), that is a genuinely new
  finding — call it out explicitly as such.
- Read the component/system/workflow YAML if you need to resolve a component name to
  its component type or a workflow task's purpose — `system.json`/`workflow.json` in
  the export mirror these, but the local config folder is the more readable source if
  both are available.

## 5. Write the deep-dive analysis

Do not stop at "experiment X improved the goal by Y%." For every finding, ask:

- **What else moved?** When a parameter change improves the goal metric, check its
  effect on every other metric in `metricsSelection` (from the per-parameter effect
  breakdown in `analysis.json`) — memory headroom, latency percentiles, temperature,
  throttling, queue depth. A throughput gain that comes with a latency or memory-margin
  cost is a trade-off worth stating explicitly, not a pure win.
- **Does it interact with another parameter?** Use the pairwise interaction scan —
  a parameter's effect that flips sign or magnitude depending on another parameter's
  value is a more useful finding than either parameter's marginal effect alone.
- **Is it robust or a single lucky trial?** With `numberOfTrials: 1` (the common case),
  a single top experiment is one sample, not a confirmed effect — cross-check against
  nearby experiments with similar parameter values before asserting a strong causal
  claim; say "consistent across N experiments with similar settings" or "a single
  best-observed point, not yet confirmed by repeats" as actually supported by the data.
- **What failed, and does it match a known cause?** Cross-reference every failed
  experiment and every `parameterConstraints`/`metricConstraintsViolations` hit against
  the README's incident log (§4). Flag anything genuinely unexplained.
- **What does the timeseries show that a single scalar hides?** Look at the curated
  timeseries charts for instability (a metric that trends up/down within a trial, or
  spikes near the end) that a trial-average would mask — call these out specifically,
  they're exactly the kind of finding a scores-table-only analysis would miss.
- **Never fabricate a number.** Every figure in the report must be traceable to
  `analysis.json`, `study.json`, or the README's own text. If the data is too noisy or
  the sample too small to support a claim, say so — a stated uncertainty is more useful
  than a false-confidence conclusion.

## 6. Produce the HTML report

Write a single, self-contained HTML file to `<study-folder>/results/report.html`
(inline CSS/JS/charts — no external CDN or network fetch, so it opens standalone from
disk in any browser). Structure it at minimum:

1. **Header** — study name, dates, goal (in plain language), pack name/version, target
   stack, link back to the study's `README.md`.
2. **Executive summary** — the handful of most important findings, each one sentence,
   written for someone who will only read this section.
3. **Results overview** — baseline vs. best-for-goal vs. best-per-KPI table (from
   `study.kpis[]`, per §2/§3), highlighting where the goal-winner and a KPI-winner
   diverge.
4. **Parameter effects & side effects** — per tuned parameter, its effect on the goal
   and on every other metric it measurably moves, narrated per §5's questions, not just
   tabulated.
5. **Parameter interactions** — the pairwise findings that matter (skip pairs with no
   real interaction rather than padding this section).
6. **Failures & constraint behavior** — failed experiments, any constraint violations
   found, cross-referenced against the README's incidents (§4), explicitly separating
   "already known" from "new" findings.
7. **Timeseries deep-dive** — the curated charts (§3), with callouts for any instability
   a scalar average would have hidden.
8. **Caveats & data-quality notes** — anything `analyze_export.py` or this skill's own
   analysis flagged as uncertain (small sample sizes, the full-series-vs-windowed-mean
   approximation, any bundle-format gap hit in §3).
9. **Recommendations** — what a follow-up study should try next, grounded in what this
   one actually showed (a narrower domain, a newly-discovered constraint to add, a
   metric worth adding to `metricsSelection`, etc.) — don't recommend something the data
   doesn't support.

Base the report's visual design on the categorical palette, mark specs, and
light/dark-aware CSS custom properties from the `dataviz` skill (load it if you have
not already this session) — the same design discipline applies to a static report as to
any other chart, even though this file isn't published through the `Artifact` tool.

## 7. Update the README(s) with a findings recap

1. **The study's own `README.md`**: if it has `## Results` / `## Conclusions` sections
   (many studies scaffolded by `akamas-study-manager` leave these as placeholders to be
   filled in once the study finishes), replace the placeholder text with a concise
   recap of the executive summary (§6.2) and a link to `results/report.html` for the
   full analysis. Leave every other section of the README untouched.
2. **`results/README.md`**: create it if it doesn't exist, or update it if it does, with
   a short recap (a few sentences, not a duplicate of the full report) plus a link to
   `report.html` — this is the first thing someone opening the `results/` folder
   directly (without reading the main README) should see.
3. Never overwrite either README wholesale — only touch the sections this step is
   responsible for.

## 8. After analysis

This skill is read-only with respect to the live Akamas instance — it never calls
`akamas` itself, only reads an already-exported bundle plus local files. If the export
looks stale (the study is still `RUNNING`, per `study.json`'s `state` field) tell the
user this report reflects a snapshot, not the final result, and that re-running
`akamas export study` and this skill again once the study finishes will produce a
complete report.
