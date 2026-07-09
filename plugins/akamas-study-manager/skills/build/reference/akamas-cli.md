# Akamas CLI — system, component, telemetry-instance, workflow & study commands

Resource aliases: `system`/`systems`/`sys`/`sy`; `component`/`components`/`comp`/`co`/`cmp`;
`telemetry-instance`/`telemetry-instances`/`ti`/`tel-instance`/`tel-inst`;
`workflow`/`workflows`/`wf`/`wkfl`/`wo`; `study`/`studies`/`st`/`sty`. Run `akamas alias` on
a configured CLI to print the full, current table — aliases are not guaranteed stable
across CLI versions.

## Dependency order

A study's dependencies must exist, in this order, before the study itself can be
created and started. Skipping ahead fails at name-resolution time (Akamas resolves
`system:`/`workflow:`/`componentType:` references by name when the referencing resource
is created, not lazily at study-start time):

1. **Optimization pack(s)** that define every `componentType` the system's components
   will use. Stock/catalog packs are installed by writing a small resource file with
   `kind: optimization-pack` and `name: <Pack Name>` and running the generic
   `akamas create -f <file>` (the `-f`/`kind:`-dispatch form). **There is no
   `akamas install -f optimization-pack <Pack Name>` command** — `install` never
   dispatches on `-f`, and it never takes a bare pack name; every `install` invocation is
   `akamas install <resource-type> <file>`, where `<file>` is a built JSON descriptor, not
   a name string. A custom pack instead needs the
   `akamas build optimization-pack <folder>` → `akamas install optimization-pack <built.json>`
   two-step (see the sibling `akamas-optimization-pack` plugin for that flow — this
   plugin does not build or install packs itself).
2. **System** — the top-level container; nothing else can be created without it.
3. **Component(s)** — each references the system (by CLI positional arg or by the
   file's own `system:` key) and a `componentType` that must already be installed.
4. **Telemetry instance(s)** — also attach to the system; a telemetry instance's
   `metrics[].name`/`.metric` should match metrics exposed by the system's component
   types, or that data has no consumer.
5. **Workflow** — standalone (no parent resource), but its tasks' `${Component.param}`
   templating and `component:`/`host:` bindings only make sense once the components they
   reference exist.
6. **Study** — references its system and workflow by name inside the YAML body
   (`system: <name>`, `workflow: <name>`); creating the study does not require them as
   CLI positional args, but they must already exist and resolve by name.
7. **Start the study.** Everything after this point (monitoring, approval, stopping,
   resuming, exporting) operates on the already-created study.

Every resource file above may instead carry a `kind:` field and be created generically
with `akamas create -f <file-or-folder>`, which dispatches on `kind:` and can batch-create
a whole mixed directory (system + components + telemetry-instance + workflow + study) in
one call — but the same dependency order still applies; Akamas resolves names at creation
time regardless of whether you used the typed or the generic form.

## System

| Action  | Command                                     | Notes |
|---------|----------------------------------------------|-------|
| Create  | `akamas create system <system.yaml>`         | No parent resource — a system is top-level |
| List    | `akamas list system`                          | `--output table\|json\|yaml`, `--no-pagination`, `--sort-asc`/`--sort-desc` |
| Get     | *(not supported)*                             | `akamas describe` explicitly does **not** support the System resource type — no CLI way to dump a single system's full detail; use `akamas list system` and filter, or `akamas export study` (bundles the referenced system) |
| Delete  | `akamas delete system <id-or-name>`           | `--force`/`-f` |

## Component

| Action  | Command                                                          | Notes |
|---------|--------------------------------------------------------------------|-------|
| Create  | `akamas create component <component.yaml> <system-id-or-name>`    | Parent = its system, required — this typed form only ever accepts a single file, **never** a folder |
| Create (bulk) | `akamas create -f <folder>/`                                 | The **generic** `-f`/`kind:`-dispatch form is the only way to batch-create components — not the typed `akamas create component ...` command above. Each file in the folder must self-describe both `kind: component` and `system: <name>`, since this form takes no resource-type or parent positional argument |
| List    | `akamas list component <system-id-or-name>`                        | `--output table\|json\|yaml` |
| Get     | `akamas describe component <id-or-name> <system-id-or-name>`      | System resource type has no `describe`, but Component does |
| Delete  | `akamas delete component <id-or-name> <system-id-or-name>`        | `--force`/`-f` |

## Telemetry instance

| Action  | Command                                                                  | Notes |
|---------|------------------------------------------------------------------------------|-------|
| Create  | `akamas create telemetry-instance <telemetry.yaml> <system-id-or-name>`  | Parent = its system, required |
| List    | `akamas list telemetry-instance`                                          | `--output table\|json\|yaml`, `--no-pagination`, `--sort-asc`/`--sort-desc` |
| Get     | `akamas describe telemetry-instance <id-or-name>`                        | `--output table\|json\|yaml` |
| Delete  | `akamas delete telemetry-instance <id-or-name> <system-id-or-name>`      | `--force`/`-f` |

## Workflow

| Action  | Command                                | Notes |
|---------|------------------------------------------|-------|
| Create  | `akamas create workflow <workflow.yaml>` | **No parent resource** — despite operationally targeting a system's components, Workflow (like Study) has no formal parent in the CLI's resource hierarchy; the link is expressed only inside task arguments (`component:`, `host:`), not a CLI positional arg |
| List    | `akamas list workflow`                   | `--output table\|json\|yaml` |
| Get     | `akamas describe workflow <id-or-name>`  | |
| Delete  | `akamas delete workflow <id-or-name>`    | `--force`/`-f` |

## Study — create

| Action  | Command                              | Notes |
|---------|----------------------------------------|-------|
| Create  | `akamas create study <study.yaml>`     | **No parent resource**, same as Workflow — the study YAML's own `system:`/`workflow:` fields are resolved by name at creation time, not passed as CLI args |
| List    | `akamas list study`                    | `--output table\|json\|yaml`, `--no-pagination`, `--sort-asc`/`--sort-desc` |
| Get     | `akamas describe study <id-or-name>`   | Full resource dump, including current state; Study (unlike System) does support `describe` |
| Delete  | `akamas delete study <id-or-name>`     | `--force`/`-f` |
| Update  | `akamas update study <id-or-name> [file] [--exploration-factor] [--safety-factor] [--engine-version] [--approval automatic\|manual]` | Tunes optimizer behavior mid-flight without stopping the study |

## Study — run, monitor, stop, resume, results

| Action | Command | Notes |
|---|---|---|
| Start | `akamas start study <id-or-name>` | Begins execution |
| Monitor progress | `akamas list experiment <study-id-or-name> [--bookmarked]` | Closest thing to "how far along is it" — lists iterations run so far; `--bookmarked` filters to auto-tagged best-so-far experiments |
| Monitor detail | `akamas list trial <study-id-or-name> [<experiment-id>]` | Trial-level detail (repeated runs of one experiment); omit experiment id for all trials in the study |
| Tail logs | `akamas log --study <id-or-name> [--exp N] [--trial N] --log-level TRACE\|DEBUG\|INFO\|WARN\|ERROR --service optimizer\|orchestrator\|...` | Scoped log tail — the closest CLI equivalent to "live progress" |
| Approve a recommendation (live studies) | `akamas update experiment <study-id-or-name> <experiment-id> --approve-configuration` | Buried under the generic `update experiment` verb, not a dedicated `approve` command; pair with `--parameter key=value` to edit before approving |
| Stop / pause | `akamas finish study <id-or-name>` | No separate `stop`/`pause` verb — `finish` covers both a genuine end and a resumable pause |
| Stop one experiment | `akamas finish experiment <study-id-or-name> <experiment-id>` | |
| Resume | `akamas resume study <id-or-name> [-m NEW\|DEL\|KEEP]` | `KEEP` (default): drop failed trials of the last experiment and continue it, or start a new one if it already has a valid result; `DEL`: drop all failed experiments, start a new one; `NEW`: unconditionally start a new experiment |
| Force a stuck trial's state | `akamas update trial <study-id-or-name> [<experiment-id>] [<trial-id>] --fail\|--finished` | Administrative escape hatch |
| Best config / results | *(no dedicated CLI verb)* | Documented path is the UI (Summary / Experiments-Highlights / Analysis tabs). From the CLI: `akamas describe study --output json` for a structured dump, or the full `akamas export study` below for everything including timeseries |
| Export (backup/migrate) | `akamas export study [--show-secrets] [-t <timeout-seconds>] <UUID\|"NAME"> [FILENAME]` | Bundles study + steps + experiments + trials + timeseries + workflow + system + components + component types + metrics + parameters + logs into one `tar.gz` |
| Import | `akamas import study [--force] [-t <timeout-seconds>] FILENAME` | Assigns new UUIDs to study/workflow/system/component/component-type/metric/parameter; keeps step/experiment/trial IDs and order; if an imported resource's *name* collides with an existing one, the existing resource wins (no overwrite, no duplicate) |

Common flags across `list`-type commands for every resource above: `--no-pagination`,
`--sort-asc`, `--sort-desc`, `--output table|json|yaml`. `delete` supports `--force`/`-f`;
`akamas delete -f <folder>` mirrors bulk-create but by default skips optimization packs
and telemetry providers even if the folder describes them — add `--complete` to remove
those too. All commands support `--debug`, `--workspace`/`-w`, `--help`.

## What's NOT available in the public CLI

- **No `validate` command** for any of these resources — `akamas create`/`akamas start`
  are the closest thing to a schema/reference check; malformed or unresolvable YAML is
  expected to fail there. This skill should do its own structural validation (required
  fields, name regexes, `system:`/`workflow:`/`componentType:` cross-references) before
  telling the user a system/study is ready to create.
- **`akamas describe` does not support the System resource type** — an explicit,
  undocumented-elsewhere CLI limitation. There is no way to dump a single system's full
  detail short of `akamas list system` (filtered) or an `akamas export study` that
  happens to reference it.
- **No `get` verb at all** — the CLI's verb is `describe`, not `get`, across every
  resource.
- **Study and Workflow have no formal parent resource** in the CLI's resource hierarchy,
  unlike Component and Telemetry Instance (both parented by System). The
  system/workflow relationship is enforced only by name-lookup inside the study's own
  YAML body, not by a positional CLI argument — an easy mistake to make when scripting
  by analogy with `create component`/`create telemetry-instance`.
- **No `stop`/`pause` verb** — use `akamas finish study`, which is overloaded to mean
  both "end for good" and "pause, resumable later" via `akamas resume`.
- **No dedicated "study status/progress" or "best configuration" verb** — monitoring and
  results are UI-first (Summary / Experiments / Analysis tabs); the CLI only offers
  `describe`/`list experiment`/`list trial`/`log`, or the full `export` tarball.
- **No dedicated "approve" command for live-study recommendations** — it's the generic
  `akamas update experiment ... --approve-configuration`, easy to miss if you're looking
  for a study-specific verb.
- **`windowing.task`, `scale` on Prometheus telemetry metrics, and the general
  "any `properties.<provider>.<key>` becomes a `$<KEY>$` query placeholder" rule** are
  real, working mechanisms confirmed against a real shipped study but are thinly or
  nowhere documented on the official schema pages — treat the bundled
  `optimization-pack-schema.md`-style tables in this skill's own schema reference as the
  authority for these, not the live docs' schema tables alone, and re-verify against
  live docs if a user's case doesn't fit the documented subset
  (`$INSTANCE$`/`$JOB$`/`$NAMESPACE$`/`$POD$`/`$CONTAINER$`/`$DURATION$`/`%FILTERS%`).
