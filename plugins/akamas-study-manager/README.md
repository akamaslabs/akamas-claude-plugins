# akamas-study-manager

A Claude Code plugin that scaffolds new **Akamas studies** — system, components,
telemetry instances, workflow, and the study manifest itself — and safely
extends existing ones. It is grounded in the official Akamas construct schemas
(system, component, telemetry-instance, workflow, study) and in the actual
optimization pack the study targets, not guesswork.

It ships one skill, invoked as `/akamas-study-manager:build`, which detects
whether you're starting a study from scratch or working inside an existing one
and adapts accordingly.

This plugin never authors the **optimization pack** itself (component types,
metric identities, parameter identities). It only reads a pack's files to know
what names it's allowed to reference. If you need to create or extend a pack,
use the sibling `akamas-optimization-pack` plugin instead.

## What it does

The `build` skill runs in one of two modes, decided automatically by whether a
top-level YAML file with `kind: study` already exists in the target directory.

Before doing anything else, it always:

- Asks for (or uses, if already given) the **optimization goal** — what you're
  trying to achieve, e.g. "maximize throughput" or "minimize p95 latency under
  an SLA".
- Resolves the **optimization pack** the study targets: a local folder path,
  or a git repo URL it clones read-only into a scratch location. It reads that
  pack's `optimizationPack.yaml`, `component-types/*.yaml`, `metrics/*.yaml`,
  and `parameters/*.yaml` so every component type, parameter (with its domain
  and default), and metric it writes into the study is one the pack actually
  declares. If no path/URL is given and cloning fails, it asks for a local
  path — it never invents names that aren't in the pack.
- Cross-checks the live Akamas docs (https://docs.akamas.io/akamas-docs) for
  anything ambiguous or not covered by its bundled schema reference — the
  bundled reference is a snapshot taken at plugin-build time, not the final
  word.

### Create mode (no `kind: study` file found)

Scaffolds a brand-new, **self-contained folder** — never scattered into an
unrelated working directory — containing:

- `<study-name>.yaml` — the study manifest (`goal`, `parametersSelection`,
  `windowing`, `steps`, ...)
- `<workflow-name>.yaml` — the workflow (`tasks:` using operators like
  `FileConfigurator`/`Executor`)
- `system/system.yaml` — the system container
- `system/components/*.yaml` — one component per piece of infrastructure being
  modeled, each referencing a component type from the target pack (or another
  already-installed pack, e.g. a stock Kubernetes/GPU component type)
- `system/telemetry/*.yaml` — the telemetry instance(s) wiring an existing
  provider (Prometheus, Dynatrace, ...) to real metric queries
- `scripts/` — helper shell scripts invoked by workflow `Executor` tasks
- `templates/` — config templates with `${Component.param}` placeholders,
  rendered by `FileConfigurator` tasks
- `README.md` — describes the study; **always states the creation date** and
  the **versions in play**: the optimization pack's name and version, the
  target software's version/image tag/model name (if known from the
  conversation or templates), and the telemetry provider used. It also
  **always includes a "Setup & run" section with every `akamas` CLI command
  needed to create every resource and start the study**, in dependency order,
  with real file paths — not just reported in chat, but persisted in the file
  itself

Before writing any of this, it asks **how configuration changes actually reach
your real target system** (a templated Kubernetes manifest applied via
`kubectl` over SSH, Ansible, a REST config API, etc.) if you haven't already
said — that decision drives which workflow operators end up in the workflow
file. It also never invents real infrastructure details — hostnames, SSH key
paths, telemetry endpoint addresses, k8s namespaces, credentials, registry
URLs. It asks for those, or leaves clearly-marked placeholders and calls them
out explicitly so you know what to fill in before running anything for real.

Before declaring the study done, it validates structurally: required fields
present, every `<Component>.<param>`/`<Component>.<metric>` reference in the
goal/constraints/`parametersSelection`/workflow templates actually resolves to
a component in the system whose component type (from the target pack) exposes
that name, and any narrowed parameter domain stays within the pack's declared
bounds.

### Modify mode (`kind: study` file found)

Makes targeted edits to an existing study:

- **Add/change a component** — new or edited file under `system/components/`
- **Add/change a telemetry metric binding** — edits `system/telemetry/*.yaml`
- **Add/change a workflow task** — edits the workflow file's `tasks:` array
- **Change the study itself** — `parametersSelection`, `goal`, `windowing`,
  `steps`, or any other top-level study field

Structural changes (a new component, a new task, a changed parameter
selection, etc.) get a "last modified" note added to the study's `README.md`,
and the README's "Setup & run" command section is kept in sync with the
change — including the delete-and-recreate commands for resources that have
no CLI update verb for the field that changed.

## What it does NOT do

- It does not run `akamas create`, `akamas build`, or `akamas start` for you —
  those require a configured, authenticated `akamas` CLI session this plugin
  has no access to. It prepares the study folder on disk and, once done, tells
  you the exact command sequence to run next (typed, in dependency order):

  ```
  akamas create system             system/system.yaml
  akamas create component          system/components/<name>.yaml "<System Name>"   # once per component file
  akamas create telemetry-instance system/telemetry/<file>.yaml  "<System Name>"
  akamas create workflow           <workflow-name>.yaml
  akamas create study              <study-name>.yaml
  akamas start study                "<Study Name>"
  ```
  The typed `create component`/`create telemetry-instance` forms only ever accept a
  single file — never a directory. For more than one component, either repeat the
  line per file, or use the bulk alternative below, which is the only form that
  accepts a whole folder (every file must self-describe its `kind:`/`system:`):
  ```
  akamas create -f <study-root>/
  ```

- It does not touch the **optimization pack** itself. It only reads the pack's
  files (locally, or cloned read-only from a git URL) to know which component
  types, parameters, and metrics it's allowed to reference by name — it never
  writes to `optimizationPack.yaml`, `component-types/`, `metrics/`, or
  `parameters/` inside the pack. If a request actually needs a new pack-side
  metric or parameter, it says so and points you at the `akamas-optimization-pack`
  plugin instead.

## Install

```
/plugin marketplace add <org>/akamas-claude-plugins
/plugin install akamas-study-manager
```

## Test locally without installing

From inside an empty directory (for create mode) or an existing study folder
containing a `kind: study` file (for modify mode):

```
claude --plugin-dir /path/to/akamas-claude-plugins/plugins/akamas-study-manager
/akamas-study-manager:build
```

## Usage examples

**Creating a brand-new study from a goal and a local pack:**

```
$ mkdir vllm-throughput-study && cd vllm-throughput-study/
$ claude
> /akamas-study-manager:build
  I want to maximize vLLM prefill + decode token throughput. The optimization
  pack is at ~/code/optimization-packs/vllm. Config changes get applied by
  rendering a Kubernetes deployment template and running `kubectl apply` over
  SSH to a jump host called toolbox.
```

The skill finds no `kind: study` file, reads the vLLM pack at the given path
(component types, parameters and their domains, metrics), asks any remaining
clarifying questions (SSH key path, target namespace, telemetry endpoint —
flagging placeholders for anything not provided), then creates
`system/system.yaml`, `system/components/vllm.yaml` (and one per other
infrastructure piece, e.g. `gpu.yaml`), `system/telemetry/prometheus.yaml`,
`W1-Optimization.yaml`, `templates/deployment_template.yaml`,
`scripts/apply_config.sh`, `throughput-study.yaml`, and a `README.md` stating
the creation date plus the pack name/version, vLLM image tag, and telemetry
provider in use.

**Modifying an existing study — adding a parameter to `parametersSelection`:**

```
$ cd vllm-throughput-study/   # already has throughput-study.yaml (kind: study)
$ claude
> /akamas-study-manager:build
  Add vLLM.tensor_parallel_size to parametersSelection with domain [1, 4]
  instead of pinning it in the baseline step.
```

The skill detects the existing `kind: study` file, confirms
`tensor_parallel_size` is a parameter the vLLM component type actually
declares (re-reading the pack if needed) and that `[1, 4]` sits within its
declared domain, adds the entry to `parametersSelection`, removes it from the
baseline step's pinned `values` map if present, and adds a "last modified"
note to the study's `README.md`.
