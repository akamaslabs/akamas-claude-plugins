# `akamas export study` bundle — file-by-file format

**This entire document is reverse-engineered from a real export bundle**, not from
`docs.akamas.io` — the public docs mention `akamas export study <UUID|"NAME"> [FILENAME]`
only as a one-line CLI reference (see the sibling `akamas-study-manager` plugin's
`reference/study-schema.md`, known-gap #9) and do not document the bundle's internal
file format at all. Treat everything here as empirically confirmed against one real,
finished offline study (vLLM throughput optimization, 83 experiments, 2 failures), not
as an authoritative schema — cross-check against a real bundle before assuming an
unseen field behaves as described here, and update this file when you find a
discrepancy.

## What the bundle is

`akamas export study ...` produces a **gzipped tar archive** (confirmed with `file` +
`tar -tzf`, regardless of what extension the file was saved with — this repo's example
is named `export.gz` but is a full `tar.gz`, not a bare gzip of one file). Extract with:

```bash
tar -xzf export.gz -C <scratch-dir>/
```

It contains a flat list of JSON files, no subdirectories:

```
study.json
system.json
workflow.json
optimizations.json
last-optimization.json
logs.json
telemetry-instance-<Provider>_<System>.json
metrics-<ComponentName>-<metricName>.json     # one file per (component, metric) pair
                                                # that ever produced at least one sample
```

## `study.json` — the single richest file; start here

A `{"study": {...}}` wrapper around one object that is the **live, fully-resolved**
study resource — richer than the authored study YAML, because it also carries
optimizer-computed summary fields that don't exist until the study has actually run.
Confirmed fields beyond the plain construct-template schema (see
`akamas-study-manager`'s `reference/study-schema.md` for the authored-YAML side of
`goal`/`windowing`/`parametersSelection`/`parameterConstraints`/`steps`, all of which
are echoed here too, fully resolved with types):

| Field | What it is |
|---|---|
| `state` | `FINISHED` / etc. — overall study state |
| `startTimestamp` / `endTimestamp` | ISO timestamps for the whole study run |
| `bestScore` | The best **normalized** goal score achieved (not the raw metric value — see `last-optimization.json` below for the distinction) |
| `bestValue` | The best **raw** goal-formula value (the actual `tokens`/`ms`/etc. unit the user thinks in) |
| `bestExperiment` | The experiment number (1-based, matches the numbering used everywhere else — see "Experiment numbering" below) that produced `bestValue` |
| `bestConfiguration` | `{ "<Component>.<param>": { "value": ..., "render": bool } }` — the full parameter set of the best experiment, including parameters NOT in `parametersSelection` (pinned/static ones), each flagged `render: false` |
| `finishedExperiments` / `experimentsWithErrors` | Counts — should sum to the total number of experiments actually run |
| `kpis` | **A short list**, NOT one entry per `metricsSelection` entry — confirmed to contain only the goal formula's own terms plus any explicitly-declared `kpis:` in the study YAML (4 entries in the reference bundle: the 2 goal terms + 2 more the user had explicitly added). Each has its own `bestExperiment` — i.e. the experiment that was individually best *for that one metric*, which is usually a **different** experiment than `study.bestExperiment` (the goal-formula winner). This divergence is exactly the trade-off signal this skill exists to surface — don't stop at `study.bestExperiment` alone. |
| `experimentsWithErrors` | Count of experiments whose **workflow itself** failed (crash, timeout) — distinct from a successful trial that merely violated a `goal.constraints` check (which would show up as a `metricConstraintsViolations` entry in `last-optimization.json`, not as an error here) |

## `last-optimization.json` — the authoritative per-experiment table

A single object (not a list) holding the **final, complete** optimizer state — for a
finished study this already contains every experiment; there is no need to reconstruct
it by walking `optimizations.json` (see below). All the arrays in it are **parallel and
index-aligned**:

```json
{
  "scores": [3640.942, 3090.38, ..., null, ...],
  "parametersAssignments": [ [ {"name": "vLLM.gpu_memory_utilization", "value": 0.92}, ... ], ... ],
  "metricConstraintsViolations": [ [], [], ... ],
  "baselineScore": 3640.942,
  "baselineExperimentIndex": 0,
  "failedExperimentsIndex": [10, 25],
  "gains": [ {"gain": 5.43, "next_x": [...]}, ... ]
}
```

- **`scores[i]`** is the **raw goal value** for that experiment (same unit/scale as
  `study.bestValue`, not the normalized `study.bestScore`) — `null` for a failed
  experiment.
- **`parametersAssignments[i]`** is that experiment's full parameter set, same
  `{name, value}` shape as `study.bestConfiguration` (but flat, no `render` flag).
- **`metricConstraintsViolations[i]`** is a list of `goal.constraints` violations for
  that experiment (empty list if none, or if the study defines no `goal.constraints` at
  all — confirmed always-`[]` in the reference bundle, which had no `goal.constraints`).
  **This is unrelated to `parameterConstraints`** — a `parameterConstraints` violation
  can never appear here, because the optimizer is not supposed to generate a parameter
  combination that violates one in the first place (see "Cross-checking
  `parameterConstraints`" below for how this skill verifies that held true in practice).
- **`gains[i]`** is optimizer-internal (predicted gain + the next normalized sample
  point `next_x` in `[0,1]` per tuned dimension) — not generally useful for a
  human-facing findings report; skip it unless specifically investigating optimizer
  behavior itself.

### Experiment numbering — the one index-mapping gotcha in this whole bundle

**Array index `i` (0-based) = experiment number `i + 1` (1-based).** Confirmed three
independent ways on the reference bundle: `baselineExperimentIndex: 0` lines up with
`study.baselineExperiment: 1`; `failedExperimentsIndex: [10, 25]` lines up exactly with
the two `exp: 11` / `exp: 26` entries seen in `logs.json`'s `ERROR`-level messages; and
`scores[20] == study.bestValue` lines up with `study.bestExperiment: 21`. Every other
per-experiment reference in the bundle (`metrics-*.json`'s
`studyExperimentTrialIds[].experiment`, `logs.json`'s `exp` field) already uses the
1-based experiment number directly — only `last-optimization.json`'s parallel arrays
are 0-based-by-position. Get this backwards and every cross-reference between the
per-experiment table and the raw timeseries silently shifts by one experiment.

### `optimizations.json` — redundant for a finished study; don't use it as the primary source

A list of **snapshots** of the same optimizer-ask state, one per "ask" the optimizer
made during the run — e.g. the reference bundle's list has 83 entries, but the entry
for a given experiment `N` only contains scores/assignments for experiments `1..N-1`
(the state as of *that* ask), not the full final history. `last-optimization.json` is
exactly the last (fullest) one of these snapshots. Use `optimizations.json` only if you
specifically need to see how the optimizer's belief evolved ask-by-ask (e.g. to inspect
`gains[].next_x` over time) — for every other purpose, `last-optimization.json` alone is
the complete, correct, and far smaller source.

## `metrics-<ComponentName>-<metricName>.json` — raw timeseries, NOT pre-aggregated

A flat JSON list, one entry per raw telemetry sample (confirmed ~30s apart, matching
the telemetry instance's own `config.duration`):

```json
{
  "value": 2724.24,
  "timestamp": "2026-07-10T14:22:17.642",
  "metric": "prefill_token_throughput",
  "studyExperimentTrialIds": [{"study": "...", "experiment": 1, "trial": 1}],
  "labels": {"componentName": "vLLM", "systemId": "...", "componentId": "...", "prometheus": "{pod=.*, model=.*}"}
}
```

- Group by `studyExperimentTrialIds[0].experiment` (1-based, matches everywhere except
  `last-optimization.json`'s arrays — see above) to get one experiment's full sample
  series for that metric.
- **The series spans the entire trial's task window** (confirmed: 32 samples ≈ 16
  minutes for a trial whose windowing trims only the `RunTest` task's own 15-minute
  benchmark run by `[5m, 1m]`), **not** the already-trimmed window the study's own
  `windowing` config uses to score the goal. A naive mean over the full series will
  therefore differ slightly from the goal `scores[i]` value in `last-optimization.json`
  (ramp-up/ramp-down samples included). This skill's bundled script cross-checks this by
  recomputing the goal formula from the raw series both with and without an
  approximated trim and comparing against `scores[i]` — **treat any per-metric mean this
  skill reports as "best-effort, full-series average," flagged as such, not as a
  byte-exact reproduction of Akamas' own windowed scoring**, unless the cross-check
  confirms a close match.
- Some metrics legitimately have far fewer samples than others in the same experiment
  (e.g. a percentile metric with `NaN` samples skipped before the first request
  completes — confirmed via `logs.json`'s `"Skipping sample for metric ...: value is
  NaN"` warnings). Don't treat a short series as a data-loss bug without checking
  `logs.json` first.

## `logs.json` — Akamas **platform** logs only, NOT the workflow task's own stdout

A flat list of ~25k structured log entries from Akamas' own internal services
(`campaign`, `telemetry`, `orchestrator`, ...), each with `loglevel`
(`INFO`/`WARN`/`ERROR`/`DEBUG`), `message`, `@timestamp`, and — only on the subset with
`"userLog": "true"` — an `exp` (experiment number, 1-based) and `trial` field tying the
entry to a specific experiment.

**Confirmed NOT present here**: the actual stdout of workflow `Executor` tasks (the
`kubectl logs`/`journalctl`/load-test output that `akamas-study-manager`'s
logging-convention rule asks every apply-config/load-test script to print). That output
is a separate CLI surface (`akamas log --study ... --service workflow`, per
`akamas-study-manager`'s bundled CLI reference), not part of this export bundle. Don't
tell a user "the workload's own logs show X" based on this file — at most, this file's
`ERROR`/`WARN` entries reveal **Akamas-side** symptoms of a failure (e.g. `"error:
deployment \"vllm\" exceeded its progress deadline"` from the orchestrator, confirming
*that* an apply/rollout failed and on *which* experiment) — not the target
application's own root-cause log line. Point the user at the live `akamas log` command
for that.

## `system.json` / `workflow.json`

Fully-resolved mirrors of the authored `system.yaml`/workflow YAML (component
`id`↔`name`↔`componentType` mapping, task list with `operator`/`arguments`), useful
mainly to label components/tasks by name in the report without needing the study's own
config folder — though this skill reads the actual config folder anyway for the parts
`study.json` doesn't carry (e.g. the README's own narrative).

## Known gaps in this document

1. Every structural claim above comes from **one** offline (non-`online`) study with a
   single-value `goal`, no `goal.constraints`, and a `trialAggregation: AVG` /
   `numberOfTrials: 1` configuration. Multi-trial aggregation
   (`trialAggregation: MAX|MIN`), live/online studies (`workloadsSelection`,
   `optimizerOptions` actually populated), and a populated `goal.constraints` /
   non-empty `metricConstraintsViolations[i]` were never observed — verify those shapes
   against a real bundle before relying on this document for one.
2. `telemetry-instance-<Provider>_<System>.json`'s own schema was not investigated in
   depth (this skill gets everything it needs about metric identity from
   `metrics-*.json`'s own `metric`/`labels` fields instead) — treat it as available but
   unexplored.
3. No confirmation of what `optimizerOptions`/`gains[].next_x` ordering means
   dimension-by-dimension — not needed for a findings report, flagged only so no one
   downstream assumes this document covers optimizer-internals debugging too.
