---
name: build
description: Scaffold a new Akamas optimization pack or safely extend an existing one (metrics, parameters, component types, telemetry providers). Trigger on explicit invocation via /akamas-optimization-pack:build, and also on natural-language requests such as "create an optimization pack for X", "scaffold an optimization pack", "add a metric/parameter/component type to this optimization pack", "add a telemetry provider to this pack", or "bump the version of this optimization pack".
---

You are helping an engineer create or extend an Akamas optimization pack. Follow the
steps below in order every time this skill runs.

## 1. Detect mode

Check whether `optimizationPack.yaml` exists in the current working directory.

- If it does **not** exist (empty directory, or a repo unrelated to an existing pack) →
  run in **Create mode** (§5).
- If it **does** exist → run in **Modify mode** (§6).

Do not ask the user which mode to use — determine it yourself from the filesystem.

## 2. Load the bundled reference material first

Before doing anything else — before asking the user any questions, before writing any
file — read both reference files that ship alongside this skill, in this skill's own
`reference/` directory:

- `reference/optimization-pack-schema.md` — the authoritative directory layout and YAML
  schema for every file type in a pack (`optimizationPack.yaml`, `component-types/*.yaml`,
  `metrics/*.yaml`, `parameters/*.yaml`, `telemetry-providers/*.yaml`), plus documented
  naming/versioning conventions and known documentation gaps.
- `reference/akamas-cli.md` — the `akamas` CLI commands for building, installing,
  upgrading, rolling back, listing, and deleting optimization packs.

Do not rely on memory of these YAML shapes — the schema has documented edge cases (e.g.
`weight: 0` in a real shipped pack despite docs saying `> 0`; `operators` being optional
in practice despite appearing required in the schema table) that only the reference
files capture. Treat these files as ground truth for the common case.

## 3. Cross-check the live Akamas docs, not just the bundled reference

The bundled reference files are a snapshot taken at plugin-build time — treat them as a
fast first pass, not the final word. Before any of the following, fetch the relevant
page(s) from the live docs instead of guessing or silently trusting the bundled
snapshot:

- Answering an ambiguous request.
- Handling an edge case not explicitly covered in `reference/optimization-pack-schema.md`
  (e.g. an unusual parameter domain, a technology-specific quirk, a CLI flag that isn't
  listed, or anything where the user's ask doesn't map cleanly onto the documented
  schema).
- Noticing that the bundled reference seems to conflict with what the user is
  describing.

Start from one of these live pages depending on the topic, and follow links from there:

- `https://docs.akamas.io/akamas-docs/reference/construct-templates/`
- `https://docs.akamas.io/akamas-docs/knowledge-base/creating-custom-optimization-packs`
- `https://docs.akamas.io/akamas-docs/reference/cli-reference/resource-management`

Prefer the live docs over the bundled reference whenever they disagree, and explicitly
tell the user about the discrepancy you found — don't silently resolve it in favor of
one source.

## 4. Hard constraints — known build-breaking pitfalls

These apply in **both** modes, to every file you write or edit. None of these are
caught by a `validate` command — there isn't one (see `reference/akamas-cli.md`) — they
only surface when `akamas build`/`install` runs, often minutes later in a CI pipeline.
Check for all of them yourself before declaring the pack done.

### 4a. Every `description` field must be ≤ 256 characters

Applies to every `description` field you write or edit: `optimizationPack.yaml`,
`component-types/*.yaml`, `metrics/*.yaml`, `parameters/*.yaml`, and
`telemetry-providers/*.yaml`.

`akamas build optimization-pack` fails if any `description` exceeds 256 characters.
This is not documented in the official schema reference — it's a real build-time
failure, so treat it as a hard limit, not a stylistic preference:

- Keep every description you generate at or under 256 characters, counting the exact
  string that will land in the YAML.
- If the user supplies or asks for a longer description, don't silently truncate it —
  shorten it while preserving the meaning, or ask the user to shorten it, and tell them
  why (the 256-character build limit).
- Treat this as part of the structural validation in both Create mode (§5) and Modify
  mode (§6) — count every description's length before declaring the pack done.

### 4b. Quote categorical values that look like booleans, numbers, or null

Applies to every `categorical` parameter domain in `component-types/*.yaml`
(`domain.categories` and the matching `defaultValue`).

YAML parses unquoted `true`, `false`, `yes`, `no`, `on`, `off`, `~`, and `null` as
native booleans/null, not strings. If a categorical parameter's `categories:` or
`defaultValue:` uses one of these unquoted, the built pack JSON gets a native JSON
boolean/null in that slot instead of a string — which breaks the build, because every
other categorical parameter in a real pack uses string values (`"auto"`, `"fcfs"`, ...)
and Akamas expects categorical values to be strings.

This is especially common because Akamas' schema has **no native boolean domain type** —
on/off flags are modeled as `categorical` with two string categories, which is exactly
where this YAML gotcha bites:

```yaml
# Correct — values explicitly quoted as strings
- name: enable_expert_parallel
  domain:
    type: categorical
    categories: ["true", "false"]
  defaultValue: "false"
```
```yaml
# Wrong — unquoted true/false become native JSON booleans in the built pack
- name: enable_expert_parallel
  domain:
    type: categorical
    categories: [true, false]
  defaultValue: false
```

Always quote such values explicitly, even though it reads redundantly. Confirmed in
practice: a pack failed its GitLab build pipeline because 5 boolean-flag parameters
(`enable_expert_parallel`, `enforce_eager`, `disable_cascade_attn`,
`async_scheduling`, `disable_custom_all_reduce`) had unquoted `true`/`false` categories
while every other categorical parameter in the same pack correctly used quoted strings —
that inconsistency is the tell to look for when auditing an existing pack.

### 4c. Pick `categorical` vs `ordinal` from the tech's own docs — never guess

Applies to every parameter you add or edit whose legal values are a fixed set of
literals, in both modes.

Akamas has two distinct domain types for this case, and they are not interchangeable —
see `reference/optimization-pack-schema.md`'s "Categorical vs ordinal" section for the
full explanation and real examples (AWS EC2's `aws_ec2_instance_size`, Node.js's
`v8_max_semi_space_size_ordinal`):

- `categorical` — values with no meaningful order (algorithm/policy names, on/off flags).
- `ordinal` — values with a real natural order (sizes, tiers, discrete power-of-2 steps),
  where list order in `categories:` encodes the rank.

Before adding any such parameter, read the actual target technology's documentation for
that setting (JVM flag reference, vLLM engine-args docs, database parameter docs, cloud
provider instance-type docs, etc.) — don't default to `categorical` just because it needs
no further thought. If the values have a real ordering, use `ordinal`. This determines how
Akamas' optimizer explores the parameter's space, so getting it wrong isn't cosmetic.

## 5. Create mode — full scaffold

Run this when no `optimizationPack.yaml` was found in the current directory.

1. **Ask the user** (skip any question already answered by their initial request):
   - The technology name and a short description of the pack.
   - Whether this is an **official Akamas-distributed pack** (needs the internal
     engineering scaffold — GitLab CI, Makefile, `deploy` ansible submodule — mirroring
     how Akamas' own packs, like `vllm`, are built) or a **standalone/custom pack**
     (public `akamas` CLI workflow only, no internal CI). **Default to standalone**
     unless the user says otherwise.
2. **Gather the initial content to model**: the metrics, parameters, and component
   type(s) the pack should expose. Get these either directly from the user, or by
   asking the user to point you at the target technology's own metrics/configuration
   documentation so you can derive them.
3. **Create the full directory tree** per the schema in
   `reference/optimization-pack-schema.md`:
   - `optimizationPack.yaml`
   - `component-types/<tech>.yaml`
   - `metrics/metrics.yaml`
   - `parameters/parameters.yaml`
   - `telemetry-providers/` — only if a custom telemetry connector is actually needed.
     Most packs don't ship one; they reuse an existing provider (Prometheus, Dynatrace,
     CSV, ...). Don't create this directory speculatively.
4. **Write a pack-level `README.md`**: a one-liner description plus a bullet list of the
   included component types (see the real vLLM-style example in
   `reference/optimization-pack-schema.md`).
5. **If the user chose "official Akamas pack"**, also scaffold:
   - `.gitlab-ci.yml` equivalent to the standard Akamas pack pipeline (build / deploy /
     e2e / cleanup / release stages).
   - `makefile` with `validate-opack` / `build` / `upload-op` / `release` targets.
   - `.pre-commit-config.yaml` with standard YAML/secret-scanning hooks.

   Tell the user explicitly that these mirror internal Akamas conventions and may need
   adjusting to their actual CI/registry credentials. **Do not invent registry URLs or
   submodule targets** — ask the user for the real values, or leave clearly-marked
   placeholders and call them out.
6. **Validate the result structurally before declaring done**:
   - Every required field is present (`name`, `description`, `version`, `weight` on
     `optimizationPack.yaml`; `name`, `description`, `parameters`, `metrics` on each
     component type; etc).
   - Name patterns match `^[a-zA-Z][a-zA-Z0-9_]*$` for component types and parameters.
   - Every parameter and metric referenced by a component type's `parameters:`/
     `metrics:` array is actually declared in `parameters/*.yaml` / `metrics/*.yaml`.
   - Every `description` field written is ≤256 characters (§4a).
   - Every categorical parameter's `categories:`/`defaultValue:` values that look like
     booleans, numbers, or null are explicitly quoted as strings (§4b).
   - Every fixed-value parameter uses `categorical` or `ordinal` correctly per the tech's
     own docs, not by default/guess (§4c).

## 6. Modify mode — targeted edits

Run this when `optimizationPack.yaml` already exists in the current directory.

1. **Ask what's changing** if not already stated: new metric / new parameter / new
   component type / new telemetry provider / other.
2. Apply the change:
   - **New metric**: add an entry to the relevant `metrics/*.yaml` (or create a new file
     if none fits), then add its `name` to the `metrics:` array of every component type
     that should expose it.
   - **New parameter**: add an entry to the relevant `parameters/*.yaml` — identity
     fields only (`name` / `description` / `unit` / `restart`) — then bind it in the
     target component type's `parameters:` array with `domain` / `defaultValue` /
     `decimals` / optional `operators`. If the domain is a fixed set of literals, decide
     `categorical` vs `ordinal` from the technology's own docs, not by default (§4c).
   - **New component type**: add a new file under `component-types/`, referencing
     existing parameters/metrics by name where possible, and declaring any genuinely new
     parameters/metrics first (in `parameters/*.yaml` / `metrics/*.yaml`) before binding
     them.
   - **New telemetry provider**: add `name` / `description` / `dockerImage` under
     `telemetry-providers/`.
3. **Always bump `version` in `optimizationPack.yaml`** for every modification — keep
   `name` identical (Akamas matches packs by name across versions), and increment the
   version following the existing `MAJOR.MINOR.PATCH` value.
4. **Guardrail — stop and confirm before proceeding** if the requested change would:
   - Rename an existing parameter, or change its `domain.type`, or
   - Rename an existing component type or metric.

   These definitions are shared instance-wide across the whole Akamas installation, and
   the docs give no guidance on backward-incompatible changes. Warn the user explicitly
   about this before making the change, and only proceed after they confirm.
5. **Update the pack's `README.md`** bullet list of component types if the set of
   component types changed.
6. **Before declaring the change done**, check §4's constraints against whatever you
   just touched — even a single new metric or parameter, not just full-pack scaffolds:
   - Every `description` field you added or edited is ≤256 characters (§4a).
   - Any categorical parameter you added or edited has its boolean/number/null-looking
     values explicitly quoted as strings (§4b).
   - Any new/edited fixed-value parameter uses `categorical` or `ordinal` correctly per
     the tech's own docs (§4c).

## 7. After either mode

Do not run `akamas build` or `akamas install` yourself — they require a configured,
authenticated `akamas` CLI session that this skill does not have. Instead, tell the user
the exact next manual steps:

```
akamas build optimization-pack <folder>
akamas install optimization-pack <built-json>      # first install
akamas install -f optimization-pack <built-json>   # upgrade
```
