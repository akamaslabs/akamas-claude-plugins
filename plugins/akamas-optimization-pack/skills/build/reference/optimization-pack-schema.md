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
| `description` | string | yes      | **≤256 characters** — `akamas build` fails on longer strings |
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
description: string    # required, ≤256 characters — build fails if longer
properties: object     # optional, free-form
parameters:             # required array — binds parameters declared in parameters/*.yaml
  - name: string                       # must match a name in parameters/*.yaml
    domain:
      type: real | integer | categorical | ordinal   # see "categorical vs ordinal" below
      domain: [min, max]               # for real/integer
      categories: [a, b, c]            # for categorical/ordinal — ALWAYS quote values that
                                        # look like YAML booleans/numbers/null (true,
                                        # false, yes, no, on, off, ~) as strings, e.g.
                                        # ["true", "false"], never [true, false]
    defaultValue: <value in domain>    # required
    decimals: 0-255                    # optional, default 5
    operators:                          # optional in practice despite docs table; only
      <OperatorName>: {...}             # needed if the parameter is applied via a
                                         # workflow operator (see workflow-operators docs)
metrics:                 # required array — binds metrics declared in metrics/*.yaml
  - name: string          # must match a name in metrics/*.yaml
```

### Categorical vs ordinal — pick the right one by reading the tech's own docs

Akamas parameters with a fixed set of literal values come in two flavors, and they are
**not interchangeable** — using the wrong one changes how the optimizer explores the
space (categorical treats every value as equally "far" from every other; ordinal exploits
the fact that values have a natural rank, so it can reason about "smaller/larger" and
interpolate between neighbors):

- **`categorical`** — a set of literal values with **no meaningful order** (e.g. a GC
  algorithm name, a scheduler policy, an on/off flag modeled as `["true", "false"]`).
  Confirmed in the authoritative schema reference (`domain->type` enum:
  `{real, integer, categorical}`).
- **`ordinal`** — a set of literal values that **do have a meaningful, real-world order**,
  even though they aren't numeric (e.g. instance sizes, discrete power-of-2 buffer sizes).
  The list order in `categories:` *is* the rank order. Confirmed against real,
  Akamas-shipped optimization packs' own parameter reference tables — not the generic
  schema page (see gap below):
  - AWS EC2 pack: `aws_ec2_instance_size` is typed **Ordinal**, domain
    `[nano, micro, small, medium, large, xlarge, 2xlarge, 4xlarge, 8xlarge, 9xlarge,
    12xlarge, 16xlarge, 18xlarge, 24xlarge]` — while the sibling `aws_ec2_instance_type`
    (a family name like `c5`/`m5`/`r5`, no natural order) is typed **Categorical**.
  - Node.js pack: `v8_max_semi_space_size_ordinal` is typed **Ordinal**, domain a list of
    power-of-2 sizes (`2, 4, 6, 8, 16, 32, ..., 32768`).

**Before adding a parameter to a pack, always read the target technology's own
documentation for that setting** (JVM flag reference, vLLM engine args, database
parameter docs, etc.) to determine whether its legal values are genuinely unordered
(→ `categorical`) or have a natural rank (→ `ordinal`) — don't default to `categorical`
just because it's the more familiar/documented type. Enum-like knobs (algorithm/policy
names, on/off flags) are `categorical`; size/tier/level-like knobs with a handful of
discrete steps are `ordinal`.

**Known gap**: the generic component-type schema reference page
(`construct-templates/component-types-template`) enumerates `domain->type` as only
`{real, integer, categorical}` — it does not list `ordinal` at all, even though real
shipped Akamas packs (above) declare parameters with type `Ordinal` in their own reference
tables. Treat `ordinal` as real and intentional (it changes optimizer behavior, it's not
just a documentation label), but cross-check the live docs/CLI before relying on the exact
literal `type: ordinal` YAML syntax for a brand-new pack — if `akamas build` rejects it,
fall back to `categorical` with `categories:` listed in ascending logical order (Akamas
normalizes categorical/ordinal domains to integer positions internally, so list order is
what encodes the rank either way).

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

Akamas has **no native boolean domain type**. On/off flags are modeled as `categorical`
with two string categories — quote them explicitly, since unquoted `true`/`false` are
parsed by YAML as native booleans and land as native JSON booleans in the built pack,
breaking the build:
```yaml
# Correct
- name: enforce_eager
  domain: { type: categorical, categories: ["true", "false"] }
  defaultValue: "false"
```
```yaml
# Wrong — breaks the build
- name: enforce_eager
  domain: { type: categorical, categories: [true, false] }
  defaultValue: false
```

## `metrics/*.yaml`

```yaml
metrics:
  - name: string          # required, no spaces, conventionally snake_case
    description: string   # required, ≤256 characters — build fails if longer
    unit: string           # optional; canonical units below, or any custom string
```
Canonical units: temporal (`nanoseconds`…`hours`), information (`bits`…`petabytes`),
`percent`. Custom strings are accepted verbatim (auto-scaled for display) — prefer the
canonical `percent` over ad hoc variants like `percentage` for consistent chart scaling.

## `parameters/*.yaml`

```yaml
parameters:
  - name: string          # required, ^[a-zA-Z][a-zA-Z0-9_]*$
    description: string   # required, ≤256 characters — build fails if longer
    unit: string           # optional
    restart: boolean       # optional, default false
```
This file declares only the parameter's **identity**. Domain, default value, decimals,
and operators are declared per-component-type in `component-types/*.yaml` — the same
parameter name can have different domains/defaults across component types that use it.

## `telemetry-providers/*.yaml` (optional)

```yaml
name: string          # required, unique instance-wide
description: string   # required, ≤256 characters — build fails if longer
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
6. All `description` fields (pack, component type, metric, parameter, telemetry
   provider) are capped at **256 characters** — `akamas build` fails on longer strings.
   This is not stated in the official schema docs; treat it as a hard limit, not a soft
   one like `weight`.
7. Categorical parameter values that look like YAML boolean/null literals (`true`,
   `false`, `yes`, `no`, `on`, `off`, `~`) must be explicitly quoted as strings in both
   `categories:` and `defaultValue:` — otherwise YAML parses them as native
   booleans/null, which land as native JSON booleans/null in the built pack JSON and
   break the build, since every other categorical parameter uses string values.
   Confirmed in practice on 5 boolean-flag parameters modeled as categorical
   (`enable_expert_parallel`, `enforce_eager`, `disable_cascade_attn`,
   `async_scheduling`, `disable_custom_all_reduce`) that had unquoted `true`/`false`
   while the rest of the pack's categorical parameters correctly used quoted strings.
8. `ordinal` is a real, distinct parameter domain type — confirmed against real shipped
   packs' own parameter tables (AWS EC2's `aws_ec2_instance_size`, Node.js's
   `v8_max_semi_space_size_ordinal`) — but the generic component-type schema page only
   documents `domain->type: {real, integer, categorical}` and never mentions `ordinal`.
   See "Categorical vs ordinal" above for how to tell them apart and what to do if
   `type: ordinal` isn't accepted at build time.
