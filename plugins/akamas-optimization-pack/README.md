# akamas-optimization-pack

A Claude Code plugin that scaffolds new **Akamas optimization packs** and safely
extends existing ones — grounded in the official Akamas optimization-pack schema
(`optimizationPack.yaml`, component types, metrics, parameters, and telemetry
providers), not guesswork.

It ships one skill, invoked as `/akamas-optimization-pack:build`, which detects
whether you're starting from scratch or working inside an existing pack and
adapts accordingly.

## What it does

The `build` skill runs in one of two modes, decided automatically by whether
`optimizationPack.yaml` already exists in the current directory.

### Create mode (no `optimizationPack.yaml` found)

Scaffolds a full pack from scratch:

- `optimizationPack.yaml` — the pack manifest (`name`, `description`, `version`, `weight`)
- `component-types/<tech>.yaml` — one or more component type definitions, binding
  parameters and metrics
- `metrics/metrics.yaml` — metric declarations
- `parameters/parameters.yaml` — parameter identities (domain/default values live
  on the component type, not here)
- `telemetry-providers/` — only created if a genuinely new telemetry connector is
  needed (most packs reuse an existing provider like Prometheus and skip this)
- a pack-level `README.md` describing the pack and its component types

If you tell it this is an **official Akamas-distributed pack**, it additionally
scaffolds the internal engineering conventions: a GitLab CI pipeline, a
`makefile` with `validate-opack`/`build`/`upload-op`/`release` targets, and a
`.pre-commit-config.yaml`. Standalone/custom packs (the default) skip all of that
and get just the pack directory.

Before declaring the pack done, it runs its own structural validation: required
fields present, name patterns valid, and every parameter/metric referenced by a
component type actually declared.

### Modify mode (`optimizationPack.yaml` already present)

Makes targeted edits to an existing pack:

- **New metric** — adds it to `metrics/*.yaml`, then wires its name into the
  `metrics:` array of the relevant component type(s)
- **New parameter** — adds its identity to `parameters/*.yaml`, then binds it
  (domain, default value, decimals, operators) in the target component type
- **New component type** — adds a new file under `component-types/`
- **New telemetry provider** — adds an entry under `telemetry-providers/`

Every change bumps `version` in `optimizationPack.yaml` (keeping `name`
unchanged, since Akamas matches packs by name across versions), and updates the
pack's `README.md` if the set of component types changed. If a change would
rename or retype something already shared instance-wide (an existing parameter's
`domain.type`, or an existing component type/metric name), the skill flags it as
a likely breaking change and confirms with you before proceeding.

## What it does NOT do

It does not run `akamas build` or `akamas install` for you — those require a
configured, authenticated `akamas` CLI session that this plugin has no access
to. Instead, it prepares the pack directory on disk and, once done, tells you
the exact commands to run next:

```
akamas build optimization-pack <folder>
akamas install optimization-pack <built-json>      # first install
akamas install -f optimization-pack <built-json>   # upgrade
```

## Install

```
/plugin marketplace add <org>/akamas-claude-plugins
/plugin install akamas-optimization-pack
```

## Test locally without installing

From inside the target optimization-pack repo (empty, for create mode, or an
existing pack, for modify mode):

```
claude --plugin-dir /path/to/akamas-claude-plugins/plugins/akamas-optimization-pack
/akamas-optimization-pack:build
```

## Usage examples

**Creating a brand-new pack:**

```
$ cd my-new-pack/   # empty directory
$ claude
> /akamas-optimization-pack:build
  I want to create an optimization pack for Redis. It's standalone, not an
  official Akamas pack. Model a "RedisServer" component type with the
  maxmemory-policy parameter and a hit_rate metric.
```

The skill detects no `optimizationPack.yaml` exists, asks any remaining
clarifying questions (description, defaults, units), then creates
`optimizationPack.yaml`, `component-types/redis.yaml`, `metrics/metrics.yaml`,
`parameters/parameters.yaml`, and a pack `README.md`.

**Adding a metric to an existing pack:**

```
$ cd optimization-packs/vllm/   # already has optimizationPack.yaml
$ claude
> /akamas-optimization-pack:build
  Add a new metric called gpu_utilization_avg to the vLLM component type.
```

The skill detects `optimizationPack.yaml` is present, adds the metric to
`metrics/*.yaml`, appends it to the `metrics:` array of the `vLLM` component
type, and bumps the pack's `version` (e.g. `1.0.1` → `1.0.2`).
