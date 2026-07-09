---
name: build
description: Create a new Akamas study from scratch, or safely modify an existing one (system, components, telemetry instances, workflow, study goal/steps/parameter selection) — everything except the optimization pack itself, which is only referenced by name/version. Trigger on explicit invocation via /akamas-study-manager:build, and also on natural-language requests such as "create an Akamas study for X", "set up a study to optimize/maximize/minimize Y", "scaffold a study against this optimization pack", "add a component/telemetry metric/workflow task to this study", or "change the goal/steps/parameter selection of this study".
---

You are helping an engineer create or modify an Akamas study — the system it runs
against, its telemetry wiring, its workflow, and the study manifest itself. You never
create or edit the optimization pack itself (component types, metric/parameter
identities); that belongs to the sibling `akamas-optimization-pack` plugin. A study only
*references* pack-declared names. Follow the steps below in order every time this skill
runs.

## 1. Detect mode

Look for a top-level YAML file in the target directory whose content includes
`kind: study`.

- If **no** such file exists (empty directory, or a repo unrelated to an existing study)
  → run in **Create mode** (§5).
- If **one** does exist → run in **Modify mode** (§6), treating that file as the study
  manifest and its directory as the study root.

Do not ask the user which mode to use — determine it yourself from the filesystem.

## 2. Load the bundled reference material first

Before doing anything else — before asking the user any questions, before writing any
file — read both reference files that ship alongside this skill, in this skill's own
`reference/` directory:

- `reference/study-schema.md` — the authoritative directory layout and YAML schema for
  every file type a study needs (`system.yaml`, `component.yaml`, `telemetry-instance.yaml`,
  the workflow file, the study manifest), the workflow-operator table, the
  `${Component.param}` / `$KEY$` templating mechanisms, the cross-resource addressing
  convention, and known documentation gaps.
- `reference/akamas-cli.md` — the `akamas` CLI commands for creating, listing,
  describing, and deleting systems/components/telemetry-instances/workflows/studies, the
  required dependency order, and the run/monitor/stop/resume verbs.

Do not rely on memory of these YAML shapes — the schema has documented edge cases (e.g.
Prometheus renaming `name`/`datasourceName` to `metric`/`datasourceMetric`; the `$KEY$`
placeholder rule being fully generic despite the docs naming only a handful of keys;
conflicting doc summaries about the `windowing` default) that only the reference files
capture. Treat these files as ground truth for the common case.

## 3. Resolve and read the referenced optimization pack

A study's entire vocabulary — every `componentType`, every parameter name/domain/default,
every metric name/unit it can legally reference — comes from an already-installed
optimization pack. **Never invent a component type, parameter, or metric name that isn't
actually declared in that pack's source.**

1. Determine the pack's location from the user's request:
   - A **local folder path** → read it directly.
   - A **git repo URL** → clone it read-only into a scratch location (e.g. a temp
     directory) — never into the study folder you're building — then read the clone.
   - If cloning fails, or neither a path nor a URL was given → ask the user for a local
     path to the pack before proceeding. Do not guess or fabricate pack contents.
2. From the pack root, read:
   - `optimizationPack.yaml` — pack `name` and `version` (you need both for the README's
     hard version-reporting requirement in §5).
   - `component-types/*.yaml` — every component type's `name`, its bound `parameters[]`
     (`name`, `domain`, `defaultValue`), and its bound `metrics[]` (`name`).
   - `metrics/*.yaml` — each metric's `name`, `description`, `unit`.
   - `parameters/*.yaml` — each parameter's `name`, `description`, `unit`, `restart`.
3. Build, in your own working memory, the exact list of component types this pack offers
   and, per component type, the exact parameters and metrics available on it (with
   domains/defaults/units). Everything you write in §5/§6 — `componentType:` fields,
   `parametersSelection[].name`, goal/KPI formulas, telemetry `metrics[].metric` entries,
   workflow template tokens — must resolve to a name on this list, or to a stock
   component type from some other already-installed pack that the user explicitly names
   (e.g. the built-in Kubernetes pack's `Kubernetes Container`, a GPU-monitoring pack's
   `GPU`) — confirm with the user before assuming any component type outside the pack you
   just read actually exists on their instance.
4. If the study needs a metric or parameter the pack doesn't declare, do not invent it or
   silently add it to the pack's files — tell the user this is a job for the
   `akamas-optimization-pack` plugin and ask how they want to proceed (e.g. pick a
   different available metric, or go extend the pack first).

## 4. Cross-check the live Akamas docs, not just the bundled reference

The bundled reference files are a snapshot taken at plugin-build time — treat them as a
fast first pass, not the final word. Before any of the following, fetch the relevant
page(s) from the live docs instead of guessing or silently trusting the bundled snapshot:

- Answering an ambiguous request.
- Handling an edge case not explicitly covered in `reference/study-schema.md` (e.g. an
  unusual workflow operator, a telemetry provider other than Prometheus, a windowing
  strategy detail, a CLI flag that isn't listed, or anything where the user's ask doesn't
  map cleanly onto the documented schema).
- Noticing that the bundled reference seems to conflict with what the user is describing.

Start from one of these live pages depending on the topic, and follow links from there:

- `https://docs.akamas.io/akamas-docs/reference/construct-templates/` (system, component,
  telemetry-instance, workflow, study, and their sub-pages: goal-and-constraints,
  windowing-strategy, parameter-selection, metric-selection, workload-selection, kpis,
  optimizer-options, steps)
- `https://docs.akamas.io/akamas-docs/reference/construct-templates/using-workflows` and
  the pages under `https://docs.akamas.io/akamas-docs/reference/workflow-operators/`
- `https://docs.akamas.io/akamas-docs/integrating/integrating-telemetry-providers/` (e.g.
  `prometheus-provider/`) for telemetry-provider-specific config shapes
- `https://docs.akamas.io/akamas-docs/reference/cli-reference/resource-management`

Prefer the live docs over the bundled reference whenever they disagree, and explicitly
tell the user about the discrepancy you found — don't silently resolve it in favor of
one source.

## 5. Create mode — full scaffold

Run this when no top-level file with `kind: study` was found in the target directory.

1. **Gather required inputs** (skip any already answered by the user's initial request):
   - The optimization goal in plain language — what to maximize/minimize, and any SLA or
     constraint (e.g. "maximize throughput", "minimize p95 latency while keeping error
     rate under 1%"). This drives `goal`/`constraints`/`kpis` in the study manifest.
   - The optimization pack's location (local path or git URL) — see §3. Do this before
     asking any technology-specific question, since the pack tells you what's actually
     available to reference.
   - **How configuration changes actually get applied to the real target system** — e.g.
     a templated Kubernetes manifest applied via `kubectl` over SSH, an Ansible
     playbook, a REST config API, a direct config-file edit + service restart, etc. This
     determines which workflow operator(s) to use (`FileConfigurator`+`Executor` for the
     templated-manifest/SSH pattern is the only pattern confirmed against a real study in
     `reference/study-schema.md`; other operators — `LinuxConfigurator`,
     `OracleConfigurator`, `WindowsExecutor`, the Spark/load-testing operators, etc. — may
     fit better depending on the answer). If not already stated, ask explicitly — do not
     default silently to the Kubernetes/SSH pattern just because it's the one documented
     example.
2. **Never invent real infrastructure details.** Hostnames, SSH key paths, Prometheus/
   telemetry endpoint addresses, Kubernetes namespaces, credentials, registry URLs, and
   similar real-world specifics must come from the user. If the user hasn't supplied
   them and you need to produce a working file (e.g. `telemetry-instance.yaml`'s
   `config.address`, a workflow task's `host.hostname`/`key`), do one of:
   - Ask the user for the real value, or
   - Write a clearly-marked placeholder (e.g. `<TELEMETRY_HOST>`, `<SSH_KEY_PATH>`,
     `<K8S_NAMESPACE>`) and explicitly call out every placeholder you left in your final
     summary to the user, so nothing silently ships as a guess.
3. **Create a new, self-contained study folder** — never scatter files into an unrelated
   current working directory. Ask the user for (or propose, then confirm) a folder name,
   and create it fresh with this layout, per `reference/study-schema.md`:
   ```
   <study-folder>/
     <study-name>.yaml          # kind: study
     <workflow-name>.yaml       # kind: workflow
     system/
       system.yaml               # kind: system
       components/
         <name>.yaml             # kind: component, one per component
       telemetry/
         <name>.yaml             # kind: telemetry-instance
     scripts/
       <name>.sh                 # helper scripts invoked by Executor tasks (run on the
                                   # remote target host, never locally)
     templates/
       <name>_template.yaml      # config templates with ${Component.param} tokens,
                                   # rendered by FileConfigurator
     README.md
   ```
   - Populate `system/components/*.yaml` with one component per component type actually
     needed, using the pack's real component-type names (and any other already-installed
     pack's component type the user has confirmed exists).
   - Populate `system/telemetry/*.yaml` with a telemetry instance whose `metrics[]`
     cover every metric the goal/constraints/KPIs will reference, using the exact
     provider-specific field names (`metric`/`datasourceMetric` for Prometheus, not the
     generic `name`/`datasourceName`).
   - Write the workflow file's tasks using the operator(s) chosen in step 1, and any
     `templates/*_template.yaml` + `scripts/*.sh` it references.
   - Write the study manifest's `goal` (and `constraints`/`kpis` if applicable),
     `windowing` (or explicitly omit it, noting the "entire trial window" default),
     `parametersSelection` (only for parameters the pack actually declares, with domains
     that are subsets of the pack's declared domain), and `steps` (typically at least one
     `baseline` step pinning known-good values, then one `optimize` step).
4. **Write the README.md in English**, well-structured, covering at minimum:
   - What the study optimizes (the goal, in plain language) and against what system.
   - **The creation date** (hard requirement).
   - **Version information** (hard requirement): the optimization pack's `name` and
     `version` (from `optimizationPack.yaml`), the target software's version/image
     tag/model name if known from the conversation or from what you wrote into
     templates/components, and the telemetry provider name (and version if known).
   - A summary of the system's components, the telemetry instance(s), the workflow, and
     the study's steps.
   - An explicit list of any placeholders left in the files (per step 2) that the user
     must fill in before running the study.
   - **A "Setup & run" section with every `akamas` CLI command needed to configure and
     launch this exact study on a real Akamas instance, in dependency order** (hard
     requirement — see §7 for the exact command set/order to use). This is not optional
     polish: the README is the persistent, self-contained record of how to run this
     study, so the full command sequence must live in the file itself, not only in your
     chat reply. Include both the typed per-resource form and the bulk `-f` alternative,
     exactly as §7 specifies, with real file paths/names substituted in (not the generic
     `<placeholders>` §7 uses when talking to the user in chat).
5. **Validate the result structurally before declaring done**:
   - Every required field is present on every resource (`kind`, `name`, `system`,
     `workflow`, etc. — see `reference/study-schema.md` per-resource tables).
   - Every `componentType:` in `system/components/*.yaml` matches a component type you
     actually confirmed exists (from the pack you read, or a name the user confirmed from
     another installed pack).
   - Every parameter/metric name used anywhere (`parametersSelection`, goal/KPI formulas,
     telemetry `metrics[].metric`, workflow template tokens, step `values`) resolves to a
     name declared by the pack and bound to the referencing component's component type.
   - Every `parametersSelection[].domain`/`categories` is a subset of the domain the
     pack's component type already declares for that parameter.
   - `windowing.task` (if set) matches an actual task `name` in the workflow file.
   - Every telemetry metric referenced by the study/goal has a producing entry in some
     telemetry instance in the same system.
   - No invented infrastructure detail slipped in unmarked — every host/key/address/
     credential/namespace is either a real value the user gave you or a flagged
     placeholder.
   - The README.md's "Setup & run" section is present and its commands actually match
     the files you created (real filenames/paths, correct system/study names, correct
     order) — not a copy-pasted generic template.

## 6. Modify mode — targeted edits

Run this when a top-level file with `kind: study` was found; treat its directory as the
study root.

1. **Ask what's changing**, if not already stated: add/change a component, add/change a
   telemetry metric binding, add/change a workflow task, or change the study's
   `parametersSelection`/`goal`/`steps` (or something else entirely).
2. Re-resolve the optimization pack (§3) before editing anything that references pack
   vocabulary, so you're validating against current pack contents, not stale memory from
   a previous run.
3. Apply the change directly to the resource file(s) it belongs to, following the same
   schema and cross-reference rules as Create mode (§5, step 5's validation checklist
   applies here too):
   - **New/changed component**: edit or add a file under `system/components/`, with a
     `componentType` you've confirmed exists.
   - **New/changed telemetry metric binding**: edit the relevant
     `system/telemetry/*.yaml`, using the provider's actual field names, and confirm the
     metric name is one some component type in the system actually exposes.
   - **New/changed workflow task**: edit the workflow file's `tasks[]`, choosing an
     operator that matches how the user says config changes are applied for real (ask if
     unclear) — do not invent host/key/address values (§5 step 2's guardrail applies
     here too).
   - **Study-level change** (`parametersSelection`/`goal`/`constraints`/`kpis`/`windowing`/
     `steps`): edit the study manifest directly. Keep any narrowed
     `parametersSelection` domain a subset of the pack's declared domain for that
     parameter.
4. **Update the README.md**:
   - Add at least a "last modified" note (date + one-line summary of the change)
     whenever the change is structural (added/removed/renamed a resource, changed the
     goal, changed which component types/metrics/parameters are in play). A purely
     cosmetic edit (e.g. fixing a typo in a description) doesn't require this, but
     default to updating it if in doubt.
   - **Update the "Setup & run" section (hard requirement, same as §5 step 4)** so it
     still reflects reality after the edit. Per §7's modify-mode guidance: if the
     resource you changed has an update verb that applies to the changed field (e.g.
     `akamas update study` for optimizer-tuning flags), replace/add that command; if not,
     state plainly in the README that the resource must be deleted and recreated, and
     give the exact `akamas delete ...` + `akamas create ...` commands for it. Never
     leave the README's command block silently stale after a structural change.
5. **Validate before declaring done**, same checklist as Create mode step 5, scoped to
   whatever you touched — including re-checking that no invented infrastructure detail
   was introduced, that every changed cross-reference still resolves, and that the
   README's "Setup & run" section matches the current state of the files.

## 7. After either mode

Do not run any `akamas` command yourself — they require a configured, authenticated
`akamas` CLI session that this skill does not have. This command set is not just a chat
reply: per §5 step 4 / §6 step 4, the exact same commands (with real file paths, not
placeholders) must already be written into the study's `README.md` before you say you're
done. Telling the user here, in chat, is a secondary confirmation of what's already
persisted in the file — never the only place these commands live. Adapt the set to what
you actually created/changed, in the correct dependency order (per
`reference/akamas-cli.md`). For a full Create-mode scaffold, that's typically:

```
akamas create system            system/system.yaml
akamas create component         system/components/<name>.yaml "<System Name>"   # repeat once per component file — the typed form takes exactly one file, never a folder
akamas create telemetry-instance system/telemetry/<file>.yaml "<System Name>"
akamas create workflow          <workflow-name>.yaml
akamas create study             <study-name>.yaml

akamas start study "<Study Name>"
```

The typed `akamas create component <file> <system-id-or-name>` form only ever accepts a
single component file — never hand the user a directory path in that slot (e.g. never
`akamas create component system/components/ "<System Name>"`, which the live Akamas CLI
does not support). If more than one component file was created, either list one typed
`akamas create component ...` line per file, or point to the bulk alternative below,
which is the only form that accepts a whole folder.

Mention the bulk alternative too (`akamas create -f <study-folder>/`, or scoped to just
the components with `akamas create -f system/components/`, since every file
self-describes its `kind:`), but note the same dependency order still applies —
Akamas resolves `system:`/`workflow:` references by name at creation time, and only the
`-f` form accepts a folder; the typed per-resource form never does.

For Modify-mode edits, only list the command(s) for the resource(s) actually changed —
e.g. just `akamas create component <file> "<System Name>"` for a brand-new component.
For an *edit to an existing* resource's YAML, check `reference/akamas-cli.md` for that
resource's own update verb (e.g. `akamas update study` exists for optimizer-tuning
fields); if no such verb applies to the field you changed, say so explicitly and point
out that the resource must be deleted and recreated — there is no generic "apply
changes" verb for system/component/telemetry-instance/workflow.

If you left any placeholders for infrastructure details (§5 step 2), remind the user of
every one of them here, in one list, so nothing is missed before they run these commands.
