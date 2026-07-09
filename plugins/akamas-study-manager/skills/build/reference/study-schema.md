# Akamas study — file structure & schema

Source: the `system-template`, `component-template`, `component-types-template`,
`telemetry-instance-template`, `study-template` (and its `goal-and-constraints`,
`windowing-strategy`, `parameter-selection`, `metric-selection`, `workload-selection`,
`kpis`, `optimizer-options`, `steps` sub-pages) pages under
https://docs.akamas.io/akamas-docs/reference/construct-templates/, the workflow schema
at `reference/construct-templates/using-workflows` and every page under
`reference/workflow-operators/`, the Prometheus provider docs under
`integrating/integrating-telemetry-providers/prometheus-provider/`, the CLI reference at
`reference/cli-reference/resource-management`, and the end-to-end CLI walkthrough at
`quick-guides/quick-guides-akamas-in-a-sandbox/aias-03-*` — all cross-verified against a
real working study on disk (Akamas' own vLLM throughput-optimization study).

This document covers **everything a study needs except the optimization pack itself**.
Component types, parameters, and metrics are *identities* declared and versioned inside
an optimization pack (see the sibling `akamas-optimization-pack` plugin's
`optimization-pack-schema.md`) — a study only **references** those names. If a name used
here (a component type, a parameter, a metric) doesn't already exist on the target
Akamas instance, the study will fail to build/run; this skill does not create packs.

## Directory layout

    <study-root>/
      <study-name>.yaml            # kind: study — the study manifest
      <workflow-name>.yaml         # kind: workflow — referenced by the study's `workflow:` field
      system/
        system.yaml                 # kind: system
        components/
          <anything>.yaml          # one or more, kind: component, each system: <system-name>
        telemetry/
          <anything>.yaml          # one or more, kind: telemetry-instance, each system: <system-name>
      scripts/
        <anything>.sh              # helper shell scripts invoked by workflow Executor tasks —
                                     # these run on the REMOTE target host the task's `host:`/
                                     # `command:` points at, never on the machine running `akamas`
      templates/
        <anything>_template.yaml   # config templates with ${Component.param} placeholders,
                                     # rendered by workflow FileConfigurator tasks into a sibling
                                     # file (conventionally the same name minus `_template`)
      README.md                    # one-liner description of what the study optimizes

Filenames under `components/` and `telemetry/` are free-form; only the `name:` field
inside each file (plus, for components, uniqueness among the system's components) is
validated. Real studies commonly use one file per component and one file per telemetry
provider, named descriptively (`gpu.yaml`, `vllm.yaml`, `prometheus.yaml`).

This whole tree is exactly the shape `akamas create -f <study-root>/` expects: every
file self-describes its resource type via `kind:` and, where relevant, its parent system
via `system:`, so one bulk command can materialize the system, its components, its
telemetry instance(s), the workflow, and the study together. Dependency order still
matters — Akamas resolves `system:`/`workflow:` references by name at creation time, so
typed single-resource commands (`akamas create system ...`, then `component`, then
`telemetry-instance`, then `workflow`, then `study`) are the safer sequence to hand back
to the user if anything might not exist yet on the target instance. See the CLI section
at the end for the full command sequence.

---

## 1. `system.yaml` (`kind: system`)

```yaml
kind: system            # required for the kind-based create/bulk-create flow

name: string             # required — no documented regex/uniqueness constraint beyond
                          # being unique enough to reference from components/telemetry-
                          # instances/studies by name; convention: no spaces
description: string      # required — free text characterizing the system
```

That's the entire schema. No `tags`, no `workspace` field, no `id` — workspace binding
happens out-of-band via CLI config/flag (`--workspace`), never inside this file. A system
is a container for components + telemetry instances; multiple studies can run against
the same system.

Real example (`system/system.yaml`):
```yaml
kind: system

name: vLLM_Benchmark
description: Benchmark for vLLM performance and optimization
```

Note `system.yaml` itself never carries a `system:` back-reference field — that field is
what *child* resources (component, telemetry-instance) use to declare which system they
belong to. `akamas describe` does **not** support the `system` resource type (an
undocumented CLI gap, not a schema issue) — use `akamas list system` instead to confirm
one exists.

---

## 2. `component.yaml` (`kind: component`)

```yaml
kind: component                    # required for kind-based create
system: string                      # required — must match an existing system's `name`

name: string                        # required, ^[a-zA-Z][a-zA-Z0-9_]*$, unique within the system
description: string                 # required
componentType: string                # required — must match the name of an EXISTING component
                                      # type. It can come from:
                                      #   (a) the optimization pack this study targets (e.g. "vLLM"), or
                                      #   (b) any OTHER already-installed pack — built-in or third-
                                      #       party — that ships a stock component type (e.g. the
                                      #       built-in Kubernetes pack's "Kubernetes Container", or a
                                      #       GPU-monitoring pack's "GPU"). A study routinely mixes
                                      #       both: one component from the pack under study, others
                                      #       from generic infrastructure packs already on the instance.
                                      # This skill does not create component types — always confirm
                                      # the named type actually exists on the target instance before
                                      # writing a component that references it.
properties: object                  # optional, free-form, nestable — see below
```

Real examples (`system/components/*.yaml`):
```yaml
kind: component
system: vLLM_Benchmark

name: container
description: Container component type
componentType: Kubernetes Container   # stock type from the built-in Kubernetes pack — no properties needed
```
```yaml
kind: component
system: vLLM_Benchmark

name: gpu
description: GPU component type
componentType: GPU                     # from a separate GPU-oriented pack, not the vLLM pack
properties:
  prometheus:
    pod: .*
    gpu: .*
```
```yaml
kind: component
system: vLLM_Benchmark

name: vLLM
description: vLLM component type
componentType: vLLM                    # from the optimization pack this study is actually about
properties:
  prometheus:
    pod: .*
    model: .*
```

### `properties` — namespacing and the telemetry query-templating contract

`properties` is documented on the component-template page only as a free-form object.
The mechanism that makes it useful is **not documented there at all** — it only shows up
in the Prometheus telemetry-provider integration docs, and is confirmed here against the
real example:

- `properties` may contain a sub-object keyed by a **telemetry provider name**
  (`prometheus` in every real example seen). This namespaces provider-specific
  properties so one component can carry distinct property sets for multiple telemetry
  providers without collision.
- Inside that provider-specific block, keys are arbitrary — whatever labels the
  underlying exporter/query needs (`pod`, `gpu`, `model`, `namespace`, `container`,
  `instance`, `job`, ...).
- When a telemetry instance's `datasourceMetric` (Prometheus) / `datasourceName`
  (generic) query string is evaluated for a given component, Akamas pre-processes the
  string, substituting `$KEY$` (the property key, upper-cased, wrapped in `$`) with that
  **component's own** property value. Values are treated as regex label matchers — hence
  real components using `.*` to intentionally match everything a query's other label
  selectors already narrow down.
- Two placeholders are documented by name for Prometheus: `instance` → `$INSTANCE$`,
  `job` → `$JOB$` (default `job` regex is `.*` if omitted from `config`). Kubernetes
  convention properties get their own named placeholders too: `namespace` →
  `$NAMESPACE$`, `pod` → `$POD$`, `container` → `$CONTAINER$`. Any *other* property not
  consumed as a named placeholder is additionally available via a generic `%FILTERS%`
  placeholder, which expands to a comma-joined block of `field=~"value"` matchers for
  every leftover key.
  **Empirically confirmed but not documented anywhere**: this substitution is actually
  generic — *any* key under `properties.<providerName>` becomes an uppercase
  `$KEY$` placeholder usable in that provider's query templates, not just the
  handful of Linux/JVM/Kubernetes keys the docs happen to name. The real example proves
  this: `gpu`/`model` are not in any documented placeholder table, yet
  `system/telemetry/prometheus.yaml` uses `$GPU$` and `$MODEL$` directly and they
  resolve correctly from `properties.prometheus.gpu` / `properties.prometheus.model`.
  Treat the documented subset as "the well-known names with dedicated docs," not as an
  exhaustive list.
- `$DURATION$` is a related but distinct placeholder — it does not come from a component
  property at all. It falls back to the telemetry instance's own `config.duration`
  value, letting one metric template's range-vector window (`[$DURATION$]`) track a
  single instance-wide setting. Some queries hardcode a literal window (e.g. `[5m]`)
  instead — legal, just decoupled from `config.duration`.

Do not confuse this `$KEY$` telemetry-templating mechanism with the *workflow-side*
`${Component.param}` templating described in §5/§7 below — they are two unrelated
substitution systems using deliberately similar-looking but different syntax
(`$KEY$` vs `${Component.param}`), resolved by different subsystems (telemetry query
evaluation vs. FileConfigurator file rendering) at different times.

### `component-type` (for completeness — not authored by a study)

A study never declares component types; it only references them by name. For reference,
a component type (declared inside a pack) binds parameters and metrics:
```yaml
name: string             # ^[a-zA-Z][a-zA-Z0-9_]*$, unique instance-wide
description: string
parameters:
  - name: string          # must exist as a declared parameter
    domain: { type: real|integer|categorical, domain: [min,max], categories: [...] }
    defaultValue: <value>
    decimals: 0-255        # optional, default 5
metrics:
  - name: string          # must exist as a declared metric
```
See the `akamas-optimization-pack` plugin's schema reference for the authoritative
version of this table — it is identical here, just referenced rather than authored.

---

## 3. `telemetry-instance.yaml` (`kind: telemetry-instance`)

### Generic/base schema

```yaml
kind: telemetry-instance     # required for kind-based create
system: string                # required — must match an existing system's `name`

provider: string               # required — name of the telemetry provider (e.g. "Prometheus")
name: string                    # optional — custom instance name
config:                         # required — provider-specific + generic settings
  schedulingTimeout: integer    # optional, seconds; default 120 (Kubernetes) / 300 (Docker)
  executionTimeout: integer     # optional, seconds; default 900
  # ...plus provider-specific keys, see below
metrics:                        # optional — provider-specific SHAPE, see override below
  - name: string                 # generic field name — Akamas metric name; MUST already be
                                  # exposed by some component type used in this system (see §7)
    datasourceName: string        # generic field name — provider-side query/metric string
    defaultValue: double           # optional — backfill value when no datapoint exists
    labels: [string]                # optional, provider-specific usage
    staticLabels: { key: value }     # optional — labels stamped onto every emitted sample
    aggregation: string               # optional, Dynatrace-only
    extras: { mergeEntities: bool }    # optional
```

### Prometheus provider override — the fields actually used in practice

**Important**: Prometheus renames the two core metric-entry fields. Where the generic
schema says `name`/`datasourceName`, Prometheus uses `metric`/`datasourceMetric`. A
reader who only skims the generic `telemetry-instance-template` page (rather than the
Prometheus provider page specifically) will write the wrong field names.

```yaml
config:
  address: string          # required
  port: integer              # required
  user: string                 # optional
  password: string              # optional
  job: string                    # optional, default ".*"
  logLevel: INFO | DETAILED       # optional
  headers: object                  # optional
  namespace: string                  # optional
  duration: integer (1-3600)          # optional — seconds; feeds $DURATION$ (see §2)
  enableHttps: boolean                 # optional (3.2.6+)
  ignoreCertificates: boolean            # optional
  disableConnectionCheck: boolean          # optional
  scope: string                              # optional — X-Scope-OrgID
  urlSuffix: string                            # optional

metrics:
  - metric: string           # required — Akamas metric name (Prometheus-specific field name)
    datasourceMetric: string  # required — PromQL string, may use $KEY$/%FILTERS%/$DURATION$
    scale: number              # UNDOCUMENTED but used in real examples — see gaps section
    labels: [string]            # optional
```

Real example (`system/telemetry/prometheus.yaml`, abridged):
```yaml
kind: telemetry-instance
system: vLLM_Benchmark

name: Prometheus
provider: Prometheus
config:
  address: kube-prometheus-stack-prometheus.monitoring.svc.cluster.local
  port: 9090
  logLevel: DETAILED
  duration: 30

metrics:
  - metric: e2e_request_latency_p95
    datasourceMetric: '(histogram_quantile(0.95, sum by(le)(rate(vllm:e2e_request_latency_seconds_bucket{model_name=~"$MODEL$", pod=~"$POD$"}[$DURATION$]))))*1000'
    scale: 1
  - metric: prefill_token_throughput
    datasourceMetric: 'sum(rate(vllm:prompt_tokens_total{model_name=~"$MODEL$", pod=~"$POD$"}[$DURATION$]))'
  - metric: gpu_util
    datasourceMetric: 'avg by(gpu)(DCGM_FI_DEV_GPU_UTIL{pod=~"$POD$", gpu=~"$GPU$"})'
```
Note the telemetry instance's `metrics:` list is a **superset/catalog** available to the
whole system — this one instance defines dozens of metrics (latency percentiles, GPU
DCGM stats, cache-hit rate, ...) while the study that consumes it only ever references
two of them (`prefill_token_throughput`, `decode_token_throughput`) in its goal formula.
That's normal: define the catalog once per system, let each study pick what it needs.

### The cross-reference contract (telemetry ↔ pack ↔ study)

1. The **pack** declares a metric's identity (`metrics/*.yaml`: `name`, `description`,
   `unit`) and a component type binds that name into its own `metrics:` array.
2. A **component** in the system is instantiated with that component type, which is how
   the metric becomes "available" on that specific component.
3. A **telemetry instance**'s `metrics[].metric` (Prometheus) / `.name` (generic) value
   must equal one of the metric names exposed by some component type used in the system
   — otherwise it's orphaned data with no consumer.
4. A **study** addresses the metric as `<ComponentName>.<metricName>` (§7) — this is how
   Akamas resolves component → component type → declared metric → the telemetry
   instance that actually produces a value for that metric name in that system.

---

## 4. `<workflow-name>.yaml` (`kind: workflow`)

```yaml
kind: workflow          # required for kind-based create; not shown on the isolated
                          # workflow schema doc pages, but present in every real example
                          # and consistent with every other resource in this directory

name: string              # required — referenced by a study's `workflow:` field
tasks:                     # required — ordered/sequential list
  - name: string            # required — this is what a study's `windowing.task` (trim
                             # windowing only) points at by exact string match
    operator: string          # required — see operator table below
    arguments: object          # required — operator-specific (see below), plus the three
                                # operator-agnostic keys below
    critical: boolean            # optional, default true — false lets the workflow
                                  # continue past this task's failure
    alwaysRun: boolean             # optional, default false — run even if a prior task failed
    collectMetricsOnFailure: boolean # optional, default false
```

**Operator-agnostic `arguments` keys** (available on every task regardless of operator):

| Argument | Type | Default | Purpose |
|---|---|---|---|
| `retries` | integer | 1 | re-run attempts on failure |
| `retry_delay` | string (`Ns`/`Nm`/`Nh`) | `5m` | wait before retrying |
| `timeout` | string (`Ns`/`Nm`/`Nh`) | infinite | max task duration before failing |

Real example (`W2-Optimization_THR.yaml`, full file) — three tasks, `FileConfigurator`
then two `Executor`s, both Executors overriding `retries: 0` and setting an explicit
`timeout`:
```yaml
kind: workflow

name: W2-Optimization_THR
tasks:
  - name: Write config
    operator: FileConfigurator
    arguments:
      source:
        hostname: toolbox
        username: akamas
        key: /work/vllm-benchmark/akamas/workflows/id_rsa
        path: /work/vllm-benchmark/akamas/templates/01-deployment_template.yaml
      target:
        hostname: toolbox
        username: akamas
        key: /work/vllm-benchmark/akamas/workflows/id_rsa
        path: /work/vllm-benchmark/akamas/templates/01-deployment.yaml

  - name: Apply config
    operator: Executor
    arguments:
      retries: 0
      timeout: 60m
      host:
        hostname: toolbox
        username: akamas
        key: /work/vllm-benchmark/akamas/workflows/id_rsa
      command: bash /work/vllm-benchmark/akamas/scripts/apply_config.sh

  - name: RunTest
    operator: Executor
    arguments:
      retries: 0
      timeout: 120m
      host:
        hostname: toolbox
        username: akamas
        key: /work/vllm-benchmark/akamas/workflows/id_rsa
      command: bash /work/vllm-benchmark/akamas/scripts/run_test_throughput.sh
```
`toolbox` here is the SSH jump host that runs `kubectl` against the target cluster —
neither the shell scripts under `scripts/` nor the rendered deployment YAML run on the
machine invoking `akamas`; everything executes on whatever `host`/`source`/`target`
points at.

### Operators — full table

Confirmed by the real example: **FileConfigurator** and **Executor**. The remaining
operators below are transcribed from the docs' `reference/workflow-operators/` pages —
best-effort, not exercised by the real example, so treat any omitted edge-case argument
as a signal to re-check the live docs before use. There is **no** Kubernetes/Docker/
Ansible/REST-specific operator in the public docs — anything container-related (as in
the real example) is done indirectly via `Executor` shelling out to `kubectl`.

| Operator | Purpose | Key arguments |
|---|---|---|
| **FileConfigurator** | Render `${Component.param}` tokens in a template and copy source→target over SSH | `source{hostname, username, password\|key, sshPort=22, path}`, `target{same shape}`, `component` (inherit source/target host+path from a component's properties instead of hardcoding), `confTemplate`, `ignoreUnsubstitutedTokens` (bool, default false) |
| **Executor** | Run a shell command over SSH | `command` (string, required), `host{hostname, username, password\|key, sshPort=22}`, `component`, `detach` (bool, default false), `replaceTemplate` (bool, default true), `confTemplate` |
| **LinuxConfigurator** | Apply Linux kernel parameters via sysctl/echo/map/command strategies | `component` (optional — omit to apply to all components); `hostname`, `sshPort=22`, `username`, `key`\|`password`, `blockDevices`, `networkDevices` |
| **WindowsExecutor** | Run a command on Windows via WinRM | `command` (required), `host{protocol=https, hostname, port=5863, path=/wsman, username, password, authType=ntlm, validateCertificate=false, ca, operationTimeoutSec, readTimeoutSec}`, `component` |
| **WindowsFileConfigurator** | Windows analog of FileConfigurator | `source{hostname, username, password, path}`, `target{same}`, `component` |
| **Sleep** | Pause the workflow | `seconds` (integer > 0, required) |
| **OracleExecutor** | Run UPDATE/DELETE SQL against Oracle (no SELECT) | `sql` (list of strings, required), `autocommit` (bool, default false), `component`, `connection{dsn \| (host+service\|sid[+port=1521]), user (required), password (required), mode: sysdba\|sysoper}` |
| **OracleConfigurator** | Apply optimizer-selected parameters to an Oracle instance | `component` (required), `connection{same shape as OracleExecutor}` |
| **SparkSSHSubmitOperator** | `spark-submit` a jar/py file via SSH to a remote node | `file`, `args`, `master`, `component` required; `deployMode=cluster`, `verbose=true`, `sshPort=22`; plus `className`, `name`, `jars`, `pyFiles`, `files`, `conf`, `envVars`, `sparkSubmitExec`, `sparkHome`, `proxyUser`, `hostname`, `username`, `password`\|`key` |
| **SparkSubmit** | `spark-submit` locally (no SSH hop) | Same required set as above minus the SSH-connection fields |
| **SparkLivy** | Submit Spark via the Livy REST service | `file`, `args`, `component` required; `className`, `name`, `queue`, `pyFiles`, `proxyUser`, `pollingInterval=10`; auto-applies experiment parameters `spark_driver_memory`, `spark_executor_memory`, `spark_total_executor_cores`, `spark_executor_cores`, `spark_num_executors` |
| **NeoLoadWeb** | Trigger a NeoLoad Web performance test | `scenarioName` or `projectId` or `projectFile{...}` (one required), `neoloadApi`, `neoloadProjectFilesApi`, `accountToken`, `lgZones`, `controllerZoneId`, `component` |
| **LoadRunner** | Run a LoadRunner Professional scenario | `controller{hostname,username,password}` required, `scenarioFile` required, `resultFolder` required (supports `{study}`/`{exp}`/`{trial}` placeholders), `loadrunnerResOverride=res`, `timeout=2h`, `checkFrequency=1m`, `executable`, `component` |
| **LoadRunner Enterprise** | Run an LRE test set | `address`, `username`, `password`, `domain`, `project`, `testId`, `testSet`, `timeSlot` (multiple of 15m, >30m) all required; `tenantID` (LR2020 only), `pollingInterval=30`, `verifySSL=true`, `component` |

### Logging convention for apply-config / load-test scripts (a plugin convention, not an Akamas schema rule)

**This is a convention this skill enforces for debuggability — it is not an
Akamas-documented or schema-verified requirement.** Nothing below is sourced from
`docs.akamas.io`; do not cite it as such, and do not let it dilute the
carefully-sourced/gap-flagged material elsewhere in this document.

**The rule**: every apply-config script/task and every load-test script/task this skill
writes (create mode) or edits (modify mode) must print the *complete* logs of the
workload/job it just touched to stdout — right after (a) confirming a config change was
applied/rolled out to the real target workload, and (b) the load-test job/process
finishes (or fails). Akamas only captures each workflow task's stdout as its per-task/
per-trial execution record; any log left only on the remote host, in a file no one
reads, or suppressed with a quiet flag is invisible when a trial needs to be debugged
after the fact.

**Kubernetes pattern — before/after.** Given the real example already documented above
(`Apply config` running `scripts/apply_config.sh`, `RunTest` running
`scripts/run_test_throughput.sh`), the scripts before this convention is applied look
like:
```bash
# scripts/apply_config.sh (before)
kubectl apply -f /path/to/rendered-deployment.yaml -n <namespace>
kubectl rollout status deployment/<name> -n <namespace> --timeout=1200s
```
```bash
# scripts/run_test_throughput.sh (before)
BENCH_FILE=/path/to/job.yaml
kubectl delete -f $BENCH_FILE ; kubectl apply -f $BENCH_FILE
kubectl wait --for=condition=complete job/<job-name> -n <namespace> --timeout=1000s
```
Extended to satisfy the convention:
```bash
# scripts/apply_config.sh (after)
kubectl apply -f /path/to/rendered-deployment.yaml -n <namespace>
kubectl rollout status deployment/<name> -n <namespace> --timeout=1200s
echo "--- Logs for deployment/<name> after config apply ---"
kubectl logs deployment/<name> -n <namespace> --all-containers --tail=-1
```
```bash
# scripts/run_test_throughput.sh (after)
BENCH_FILE=/path/to/job.yaml
kubectl delete -f $BENCH_FILE ; kubectl apply -f $BENCH_FILE
kubectl wait --for=condition=complete job/<job-name> -n <namespace> --timeout=1000s
echo "--- Logs for job/<job-name> ---"
kubectl logs job/<job-name> -n <namespace> --all-containers --tail=-1
```
If the load-test job can fail rather than complete, run the `kubectl logs` line
unconditionally (or in both the success and failure branch) so a failing trial is just
as debuggable as a passing one — don't gate the log dump behind `kubectl wait` exiting 0.

**Generalization for non-Kubernetes mechanisms:**
- **SSH + service-restart** (a raw `Executor` command, no Kubernetes involved): after
  restarting the service, dump its log source to stdout before the task ends — e.g.
  `journalctl -u <service> --no-pager -n 500` or `tail -n 500 /var/log/<service>/*.log`.
  Equally, once the load-test tool finishes, print its output/log file's contents to
  stdout (e.g. `cat <result-file>`) rather than leaving it only on disk.
- **Ansible-based apply** (`Executor` running `ansible-playbook ...`): run it without
  suppressing output — no `-q`, no redirect to `/dev/null` — so its own task-level output
  (which already shows what changed) reaches stdout. If the playbook itself doesn't
  surface the target service's own logs, add an explicit follow-up step that does (same
  `journalctl`/`tail` idea as above).
- **Dedicated, non-script operators** (`OracleConfigurator`, `LoadRunner`,
  `LoadRunner Enterprise`, `NeoLoadWeb`, `SparkSubmit`/`SparkSSHSubmitOperator`/
  `SparkLivy`) have no raw script for this skill to extend with a `kubectl logs`-style
  line. **Caveat**: for these, the convention translates to "don't disable or skip
  whatever built-in output/report visibility that operator already offers" (e.g. don't
  turn off `LoadRunner`'s result-folder reporting, don't strip verbosity flags) — this
  skill cannot literally inject a log-dump step into an operator it doesn't control the
  internals of, and should say so if asked to apply this convention to one of them.

**The one universal, always-actionable rule**: on any raw `Executor` script, never
suppress or discard the target workload's/job's own stdout or log output — no
`> /dev/null`, no `--quiet`/`-q` flags on the workload's own log/report tooling — and
explicitly fetch and print logs whenever the apply/launch command itself doesn't already
stream them (`kubectl apply`/`ansible-playbook` only stream their *own* operation's
output, not the target application's logs, which is exactly why an explicit
`kubectl logs`/`journalctl`/`tail` call is required on top).

When this skill edits a pre-existing apply-config or load-test script that is missing
this pattern, it must add it as part of the edit and explicitly tell the user it did so
— never silently leave a script without complete log output while touching it for an
unrelated reason.

---

## 5. `<study-name>.yaml` (`kind: study`)

### Top-level fields

```yaml
kind: study                         # required for kind-based create

name: string                          # required
system: string                         # required — name (or id) of an existing system
workflow: string                        # required — name (or id) of an existing workflow

goal: object                             # required — see below
kpis: [object]                            # optional — see below; derived from goal+constraints if omitted
windowing: object                          # optional — entire trial window used if omitted
parametersSelection: "all" | [object]       # optional, default "all"
metricsSelection: "all" | [string]           # optional, default "all" — recording only, no effect on optimization
workloadsSelection: [object]                  # optional — live optimization only
numberOfTrials: integer                        # optional, default 1 — study-wide default, overridable per step
trialAggregation: MAX | MIN | AVG                # optional, default AVG
requireApproval: boolean                          # optional, default false (true if workloadsSelection present)
optimizerOptions: object                           # required for LIVE studies; unused in offline studies
steps: [object]                                     # required — see below
```

### `goal`

```yaml
goal:
  objective: maximize | minimize     # required
  function:                            # required
    formula: string                     # required — arithmetic over <Component>.<metric> tokens:
                                          # + - * / ^, plus sqrt()/log()/max()/min()
    variables:                            # optional
      <var_name>:
        metric: string                     # metric or <Component>.<metric>
        labels: { key: value }              # optional
        aggregation: AVG | MIN | MAX          # optional
  constraints:                            # optional
    absolute:
      - name: string
        formula: string                    # "<Component>.<metric> <op> <threshold>", op: > < <= >= == !=
    relativeToBaseline:
      - name: string
        formula: string                    # "<Component>.<metric> <op> <percent>%"
```

Real example — a two-term sum, no `variables`/`constraints`:
```yaml
goal:
  objective: maximize
  function:
    formula: vLLM.prefill_token_throughput + vLLM.decode_token_throughput
```

### `windowing`

If omitted, the entire trial time window is scored (there is a conflicting doc-page
summary claiming a `"trim"` default — the dedicated windowing-strategy page's explicit
statement, "if not specified, the entire time window is considered," is the one to
trust; flag this contradiction to a user if it matters to them).

```yaml
# type: trim
windowing:
  type: trim
  trim: [string, string]     # required — [start-offset, end-offset], e.g. "5m"/"1m"/"0s";
                               # offsets can be pinned with @start/@end for fixed-width windows
  task: string                 # optional — name of a task in this study's workflow; when
                                 # given, trim[0] is computed from THAT task's start instead
                                 # of the trial's start
# type: stability
windowing:
  type: stability
  stability:
    metric: string               # required
    labels: { componentName: string }  # optional filter
    resolution: string               # optional, e.g. "30s"
    width: number                     # required
    maxStdDev: number                  # required — stability threshold
  when:
    metric: string                      # required — metric to optimize within stable windows
    labels: { componentName: string }    # optional
    is: min | max                         # required
```

Real example — trim windowing scoped to a specific task:
```yaml
windowing:
 type: trim
 trim: [5m, 1m]
 task: RunTest
```
`RunTest` is the exact `name` of the third task in `W2-Optimization_THR.yaml` (the
`Executor` task that runs the benchmark job) — this discards the first 5 minutes and
last 1 minute of *that task's own* execution window, not the whole trial.

### `parametersSelection`

```yaml
parametersSelection: all              # default — every parameter on every component is tunable
# or:
parametersSelection:
  - name: string           # required — "<ComponentName>.<paramName>"; the parameter must
                             # already be bound to that component's component type
    domain: [number, number]  # optional, real/integer only
    categories: [string]        # optional, categorical only
```
**Confirmed constraint**: a narrowed `domain`/`categories` here must be a sub-range/
subset of the domain the pack's component type already declares for that parameter — it
narrows the pack-level domain for this study only, it never widens or overrides it.

Real example — three narrowed real-valued sub-ranges:
```yaml
parametersSelection:
  - name: vLLM.gpu_memory_utilization
    domain: [0.8, 0.95]     # ⊂ the vLLM component type's declared [0.0, 1.0]
  - name: vLLM.max_num_seqs
    domain: [32, 512]
  - name: vLLM.max_num_batched_tokens
    domain: [512, 10240]
```
Note two parameters used in the same study's baseline step (`vLLM.tensor_parallel_size`,
`vLLM.max_model_len`) are **not** in `parametersSelection` at all — they're pinned to
fixed values via the baseline step's `values` map, which is independent of, and not
restricted by, `parametersSelection`. Pinning ≠ tuning.

### `metricsSelection` / `workloadsSelection` (siblings of `parametersSelection`)

```yaml
metricsSelection: all                 # default
metricsSelection:
  - string                              # "<ComponentName>.<metricName>" — recording/tracking
                                          # only, does NOT affect the optimizer

workloadsSelection:                     # live optimization only
  - name: string                          # "<ComponentName>.<metricName>[:aggregation]"
                                            # aggregation: avg|min|max|sum|p90|p95|p99, default avg
```

### `kpis` (offline studies)

```yaml
kpis:
  - name: string             # optional, defaults to the metric name
    formula: string            # required — "<ComponentName>.<metricName>"
    direction: minimize | maximize   # required
    aggregation: avg|min|max|sum|p90|p95|p99  # optional, default avg
```
If omitted entirely (as in the real example), every metric referenced in `goal` and
`constraints` automatically becomes a KPI.

### `optimizerOptions` (required for live studies only)

```yaml
optimizerOptions:
  onlineMode: RECOMMEND | FULLY_AUTONOMOUS
  safetyMode: LOCAL | GLOBAL
  safetyFactor: number       # 0..1, default 0.6 live / 0.5 offline
  workloadOptimizedForStrategy: LAST | MOST_VIOLATED | MAXIMIN
  explorationFactor: number | FULL_EXPLORATION   # 0..1
  trialsWithBeta: integer
```
Not present in the real (offline) example at all.

### `steps`

Common fields on every step: `name` (required), `type` (required — one of
`baseline`/`bootstrap`/`preset`/`optimize`), `runOnFailure` (optional, default false).

```yaml
# type: baseline — run one experiment as the study's reference point
- name: string
  type: baseline
  numberOfTrials: integer          # optional, default 1
  values: { <Component>.<param>: <value> }   # optional; mutually exclusive with `from`
  from:                              # optional; mutually exclusive with `values`
    - study: string
      experiments: [integer]
  renderParameters: string             # optional
  doNotRenderParameters: string          # optional

# type: optimize — the actual search loop
- name: string
  type: optimize
  numberOfExperiments: integer      # REQUIRED, > 0, ≥ numberOfInitExperiments
  numberOfTrials: integer            # optional, default 1
  numberOfInitExperiments: integer    # optional, default 10; < numberOfExperiments;
                                        # ignored by SOBOL/RANDOM optimizers
  maxFailedExperiments: integer         # optional, default 30, > 1 — step aborts once
                                          # exceeded (counts workflow errors + constraint
                                          # violations)
  optimizer: AKAMAS | SOBOL | RANDOM      # optional, default AKAMAS

# type: bootstrap — reuse experiments already run in other studies
- name: string
  type: bootstrap
  from:
    - study: string
      experiments: [integer]   # optional — omit to import all

# type: preset — run one experiment at a specific already-known configuration
- name: string
  type: preset
  numberOfTrials: integer   # optional, default 1
  values: { ... }             # mutually exclusive with `from`
  from:
    - study: string            # optional, defaults to current study
      experiments: [integer]    # required, single experiment number
```

Real example — one pinned `baseline` step, one open-ended `optimize` step:
```yaml
steps:
  - name: baseline
    type: baseline
    numberOfTrials: 1
    values:
      vLLM.gpu_memory_utilization: 0.9
      vLLM.max_num_seqs: 256
      vLLM.max_num_batched_tokens: 4096
      vLLM.tensor_parallel_size: 1
      vLLM.max_model_len: 32768

  - name: optimize
    type: optimize
    numberOfExperiments: 1000
    maxFailedExperiments: 1000
```
Flag to anyone copying this pattern: `maxFailedExperiments` (1000) equals
`numberOfExperiments` (1000), which effectively disables the failure guard the docs
describe (default 30) — the step can never abort early on failures since it would need
more failures than its entire experiment budget. Legitimate, but worth calling out
explicitly since it silently opts out of a safety default.

---

## 6. Workflow-side templating: `${Component.param}` (distinct from telemetry `$KEY$`)

A config template rendered by a `FileConfigurator` task uses `${ComponentName.paramName}`
tokens — `ComponentName` must be the `name` of a component in the study's system, and
`paramName` must be a parameter bound to that component's component type. Real example
(`templates/01-deployment_template.yaml`, excerpt):
```yaml
args:
  - "--gpu-memory-utilization=${vLLM.gpu_memory_utilization}"
  - "--max-num-seqs=${vLLM.max_num_seqs}"
  - "--max-num-batched-tokens=${vLLM.max_num_batched_tokens}"
  - "--tensor-parallel-size=${vLLM.tensor_parallel_size}"
```
`FileConfigurator` renders the template file at `source.path` (fetched from the host in
`source`) into `target.path` (written to the host in `target`), substituting every
`${Component.param}` token with the value the optimizer chose for that parameter in the
current trial, then a later `Executor` task typically applies the rendered file (e.g.
`kubectl apply -f ...`). This is a **separate mechanism** from the telemetry-side
`$KEY$`/`%FILTERS%` placeholder substitution described in §2 — same dollar-sign
aesthetic, different syntax (`${A.b}` vs `$B$`), different subsystem, different timing
(file-render time vs. query-evaluation time). Don't conflate the two when explaining
either to a user.

---

## 7. Cross-resource addressing convention: `<ComponentName>.<name>`

Confirmed consistently across `goal.function.formula`, `goal.constraints`,
`kpis[].formula`, `parametersSelection[].name`, `metricsSelection[]`,
`workloadsSelection[].name`, step `values` keys, and workflow `${...}` template tokens:

**The left-hand side is the component's own `name` field (from its `kind: component`
YAML), not its `componentType`.** These can differ — e.g. the real system's `gpu`
component has `name: gpu` but `componentType: GPU`, and `container` has `name: container`
but `componentType: "Kubernetes Container"`. Resolution chain for the right-hand side:

1. Look up the component named on the left inside the study's `system`.
2. Read that component's `componentType`.
3. Confirm the named metric/parameter is bound to that component type (in the pack that
   declares the component type) — this is where the reference is validated against
   pack-declared identities.
4. For a **metric**: find the telemetry instance in the same system whose `metrics[]`
   entry produces that exact metric name (see §3's cross-reference contract).
   For a **parameter**: the value either comes from `parametersSelection`'s domain (if
   tuned) or a step's `values` map (if pinned) — either way it's the optimizer/step that
   supplies the concrete value, then a workflow's `${Component.param}` token or
   operator-specific mechanism (e.g. `OracleConfigurator`) applies it to the real system.

This skill (study-manager) never creates the pack-side identities being referenced — it
only writes files that name them correctly and can validate that a name used in a study/
workflow/component actually resolves to something declared by an already-installed pack,
if that pack's source is available to inspect.

---

## 8. Explicitly OUT of scope here (belongs to the optimization pack instead)

- **Component types** (`name`, `description`, `parameters[]`, `metrics[]` bindings) —
  defined and versioned inside a pack's `component-types/*.yaml`. This study tooling
  only references a component type by name inside a `component.yaml`'s `componentType`
  field; it never authors the component type itself.
- **Metric identities** (`name`, `description`, `unit`) — defined inside a pack's
  `metrics/*.yaml`. A telemetry instance's `metrics[].metric` and a study's
  `<Component>.<metric>` references presuppose the name already exists there.
- **Parameter identities** (`name`, `description`, `unit`, `restart`) — defined inside a
  pack's `parameters/*.yaml`. A study's `parametersSelection`/step `values` and a
  workflow template's `${Component.param}` presuppose the name already exists there, and
  that it's bound (with a domain/default) to the referenced component's component type.
- **Telemetry providers** (`name`, `description`, `dockerImage`) — a brand-new connector
  implementation, distinct from a **telemetry instance** (which this study tooling *does*
  create — it's the wiring of an existing provider to this specific system).

If a user's request touches any of the above (e.g. "add a new parameter to the vLLM
component type," or "this pack doesn't have a metric for X yet"), that's a job for the
`akamas-optimization-pack` plugin, not this one — point them there.

---

## 9. Known documentation gaps (don't treat these as hard failures)

1. **`properties.<providerName>.<key>` → `$<KEY>$` is a general rule, not documented as
   one.** The docs only enumerate a fixed subset of placeholder names tied to built-in
   Linux/JVM/Kubernetes component types (`instance`, `job`, `namespace`, `pod`,
   `container`, `duration`, plus the `%FILTERS%` catch-all). The real example proves the
   substitution is actually generic — arbitrary keys like `gpu`/`model` become
   `$GPU$`/`$MODEL$` and resolve correctly — but no page states this outright. Treat it
   as empirically confirmed, not doc-confirmed, and mention the gap if a user is building
   a custom component type's properties for the first time.
2. **`scale` on a Prometheus metric entry is completely undocumented.** Real metrics
   frequently carry `scale: 1` alongside a `datasourceMetric` that already does its own
   `*1000` unit conversion inline. Presumed to be a unit-scaling multiplier applied to
   the raw query result, but no page confirms its exact semantics or default. Don't
   assert behavior beyond "it exists and real packs use it."
3. **`windowing` default behavior has two contradicting doc summaries** — one table entry
   claims omitting `windowing` defaults to `type: trim`; the dedicated windowing-strategy
   page says the entire trial window is used instead. Trust the dedicated page (no
   trimming by default); flag the contradiction if a user's expectations hinge on it.
4. **`kind:` on workflow/study/telemetry-instance files** is never shown on the isolated
   per-resource schema doc pages (they show only the bare fields), but is present and
   required for the bulk `akamas create -f <folder>/` flow, and every real example file
   in this study uses it. Not a contradiction — just an omission on the "single resource,
   single command" doc pages versus the "-f/bulk" doc pages.
5. **No dedicated `validate` command** for any of these resources, same gap already
   logged for optimization packs. `akamas build`/`create` are the closest thing to a
   schema check; this skill should do its own structural validation (required fields,
   name-resolution against the referenced pack if available, `windowing.task` matching an
   actual workflow task name, `parametersSelection` domains staying within pack-declared
   bounds) before telling a user their study is ready to create.
6. **`describe` does not support the `system` resource type** — an explicit CLI
   limitation, not a schema issue; use `akamas list system` to confirm a system exists
   instead.
7. **Study and Workflow have no CLI "parent resource"** even though a study obviously
   depends on a system and a workflow — that dependency is enforced only by name
   resolution inside the YAML body (`system:`, `workflow:` fields) at creation time, not
   by a positional CLI parent argument the way `component`/`telemetry-instance` require a
   system argument.
8. **No dedicated Kubernetes/container workflow operator** exists despite Akamas' own
   vLLM study being entirely Kubernetes-based — confirming that "generic `Executor`
   shelling out to `kubectl`" is the intended pattern for k8s targets, not a gap in this
   research.
9. **No CLI verb for "status of a running study" or "best configuration so far."**
   Monitoring is UI-first; the CLI only offers `describe study`, `list experiment`,
   `list trial`, and `akamas log --study ...`. `akamas export study` bundles everything
   (study/steps/experiments/trials/timeseries/workflow/system/components) into a tarball
   if a user needs the full data outside the UI.
10. **No separate pause/stop verb** — `akamas finish study <id|name>` is overloaded to
    mean both a permanent stop and a resumable pause; resume with
    `akamas resume study <id|name> [-m NEW|DEL|KEEP]` (default `KEEP`).
11. **A third, undocumented templating syntax exists alongside `$KEY$` and
    `${Component.param}`.** The real example's telemetry instance uses
    `histogram_quantile(${percentile}, ...)` in two metrics
    (`fleet_e2e_latency_percentile`, `fleet_inter_token_latency_percentile`) — a
    `${...}` token inside a `datasourceMetric` query, distinct from both the
    component-properties `$KEY$` mechanism and the workflow's `${Component.param}`
    mechanism. No doc page confirms what substitutes `${percentile}` or when this form
    is legal versus the other two. Treat any `${...}` or `$KEY$` token you didn't
    author yourself as suspect, and ask the user (or flag it) rather than assuming it
    resolves the way the other two mechanisms do.

---

## CLI command sequence (for reference — this skill prepares files, it doesn't run these)

```bash
# Typed, single-resource form (safer ordering, works even without kind:/system: fields)
# IMPORTANT: the typed `akamas create <type> <file> <system>` form takes exactly ONE file
# per call. There is no folder-accepting variant of the typed command — per the live CLI
# reference, only the bulk `-f` form (below) operates on a whole folder, and that form
# drops the resource-type/system positional args entirely rather than reusing them.
# Repeat the `component`/`telemetry-instance` line once per file when a directory (e.g.
# system/components/) holds more than one, e.g.:
akamas create system             system/system.yaml
akamas create component          system/components/container.yaml "<System Name>"
akamas create component          system/components/gpu.yaml       "<System Name>"
akamas create component          system/components/vllm.yaml      "<System Name>"
akamas create telemetry-instance system/telemetry/prometheus.yaml "<System Name>"
akamas create workflow           <workflow-name>.yaml
akamas create study              <study-name>.yaml

akamas start study "<Study Name>"
```
```bash
# Bulk form — not merely "the typed commands but pointed at a folder": it drops the
# resource-type and system positional args shown above entirely and instead dispatches
# purely on each file's own kind:/system: fields. Every file in the tree must self-describe
# both for this form to work.
akamas create -f <study-root>/
```
Monitoring/lifecycle, once running:
```bash
akamas describe study <id|name> --output json
akamas list experiment <study-id|study-name> [--bookmarked]
akamas list trial <study-id|study-name> [<experiment-id>]
akamas log --study <id|name> [--exp N] [--trial N] --log-level INFO --service optimizer
akamas finish study <id|name>          # stop or pause (resumable)
akamas resume study <id|name> [-m NEW|DEL|KEEP]
akamas export study <UUID|"NAME"> [FILENAME]
```
