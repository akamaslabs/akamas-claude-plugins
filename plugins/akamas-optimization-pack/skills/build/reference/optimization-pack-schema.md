# Akamas optimization pack — file structure & schema

Source: https://docs.akamas.io/akamas-docs/knowledge-base/creating-custom-optimization-packs
and the construct-templates reference pages under https://docs.akamas.io/akamas-docs/reference/construct-templates/,
cross-verified against a real shipped pack (Akamas' own `vllm` optimization pack).

## Directory layout

    <pack-root>/
      optimizationPack.yaml        # required manifest
      component-types/
        <anything>.yaml            # one or more files, filenames don't matter
      metrics/
        <anything>.yaml
      parameters/
        <anything>.yaml
      telemetry-providers/         # optional — only for a brand-new connector type
        <anything>.yaml

Filenames are free-form; only the `name:` fields inside each file are validated/unique.
Real packs commonly use one flat file per directory, named after the technology
(`vllm.yaml`, `metrics.yaml`, `parameters.yaml`).

## `optimizationPack.yaml`

| Field         | Type   | Required | Constraints                          |
|---------------|--------|----------|---------------------------------------|
| `name`        | string | yes      | no spaces; identity used across versions/upgrades |
| `description` | string | yes      | —                                      |
| `version`     | string | yes      | `MAJOR.MINOR.PATCH`                    |
| `weight`      | int    | yes      | docs say `> 0`, but a real shipped pack uses `0` — don't hard-fail on 0, flag it instead |
| `tags`        | array  | no       | default `[]`                           |

Example (real, from the vLLM pack):
```yaml
name: vLLM
description: Optimization pack for vLLM
version: 1.0.1
weight: 0
```

## `component-types/*.yaml`

```yaml
name: string           # required, ^[a-zA-Z][a-zA-Z0-9_]*$, unique instance-wide
description: string    # required
properties: object     # optional, free-form
parameters:             # required array — binds parameters declared in parameters/*.yaml
  - name: string                       # must match a name in parameters/*.yaml
    domain:
      type: real | integer | categorical
      domain: [min, max]               # for real/integer
      categories: [a, b, c]            # for categorical
    defaultValue: <value in domain>    # required
    decimals: 0-255                    # optional, default 5
    operators:                          # optional in practice despite docs table; only
      <OperatorName>: {...}             # needed if the parameter is applied via a
                                         # workflow operator (see workflow-operators docs)
metrics:                 # required array — binds metrics declared in metrics/*.yaml
  - name: string          # must match a name in metrics/*.yaml
```

Real example (vLLM, abridged):
```yaml
name: vLLM
description: vLLM
parameters:
  - name: gpu_memory_utilization
    domain: { type: real, domain: [0.0, 1.0] }
    defaultValue: 0.9
  - name: max_num_seqs
    domain: { type: integer, domain: [1, 1000000000000] }
    defaultValue: 128
metrics:
  - name: e2e_request_latency_p95
  - name: request_success_rate
```

## `metrics/*.yaml`

```yaml
metrics:
  - name: string          # required, no spaces, conventionally snake_case
    description: string   # required
    unit: string           # optional; canonical units below, or any custom string
```
Canonical units: temporal (`nanoseconds`…`hours`), information (`bits`…`petabytes`),
`percent`. Custom strings are accepted verbatim (auto-scaled for display) — prefer the
canonical `percent` over ad hoc variants like `percentage` for consistent chart scaling.

## `parameters/*.yaml`

```yaml
parameters:
  - name: string          # required, ^[a-zA-Z][a-zA-Z0-9_]*$
    description: string   # required
    unit: string           # optional
    restart: boolean       # optional, default false
```
This file declares only the parameter's **identity**. Domain, default value, decimals,
and operators are declared per-component-type in `component-types/*.yaml` — the same
parameter name can have different domains/defaults across component types that use it.

## `telemetry-providers/*.yaml` (optional)

```yaml
name: string          # required, unique instance-wide
description: string   # required
dockerImage: string   # required — image implementing the extraction logic
```
Only needed when introducing a data source Akamas doesn't already support. Most packs
omit this entirely and rely on existing providers (Prometheus, Dynatrace, CSV, ...).

## Explicitly OUT of scope for an optimization pack

- **Telemetry instances** (wiring a provider to a specific system's live metrics) —
  workspace/system-level, created separately, not shipped in a pack.
- **Workflows** (`tasks: [{name, operator, arguments, ...}]`) — authored per system, not
  inside a pack. A component type's `parameters[].operators` field *references* an
  operator by name; the workflow YAML itself lives elsewhere.
- **Goals/KPIs** — declared inside an optimization *study* manifest (`goal`, optional
  `kpis`), referencing metric names that a pack already defines. Never scaffold a
  `kpis/` directory inside a pack.

## Naming & versioning conventions

- Component type / parameter names: `^[a-zA-Z][a-zA-Z0-9_]*$`, unique **instance-wide**
  (shared across all workspaces on one Akamas installation, not per-pack).
- Metric names: no spaces; snake_case by convention.
- Version bumps on an existing pack: **keep `name` identical**, increment `version`.
  Akamas matches packs by name for upgrade/rollback.
- Renaming or retyping an existing shared parameter/component type across versions is
  an undocumented, likely breaking change — warn before doing it.

## Known documentation gaps (don't treat these as hard failures)

1. No public `akamas validate optimization-pack` command — only `build` (which likely
   fails on schema errors) and `install`/`create` (which likely reject bad JSON).
2. `weight` documented as `> 0` but a real shipped pack uses `0`.
3. `operators` on component-type parameters is documented as required in the schema
   table but is optional/absent in real examples and shipped packs.
4. No official "extending an existing pack" walkthrough — modification guidance here is
   synthesized from the schema plus the one-line upgrade instruction in the creation doc.
5. No documented guardrails for breaking changes to shared parameter/component-type
   definitions across pack versions.
