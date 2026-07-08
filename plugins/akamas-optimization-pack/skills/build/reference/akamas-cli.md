# Akamas CLI — optimization-pack commands

Resource aliases: `optimization-pack`, `optimization-packs`, `op`, `opt-pack`, `opack`.

| Action    | Command                                                        | Notes |
|-----------|-------------------------------------------------------------------|-------|
| Build     | `akamas build optimization-pack <folder>`                       | Compiles the pack folder into one JSON descriptor |
| Create    | `akamas create optimization-pack <resource-file>`                | For registering a pack resource; custom packs can skip `kind` and supply built JSON directly |
| Install   | `akamas install optimization-pack <path-to-json>`                | Instance-wide, admin operation |
| Upgrade   | `akamas install -f optimization-pack <path-to-json>`             | Same `name`, higher `version` |
| Rollback  | `akamas install -f optimization-pack -v <OLD_VERSION>`           | Reinstalls a previous version |
| Uninstall | `akamas uninstall optimization-pack <id>`                        | `--force`/`-f` to force |
| List      | `akamas list optimization-pack`                                  | `--output table\|json\|yaml` |
| Delete    | `akamas delete optimization-pack <id-or-name>`                   | `--force`/`-f`, `--complete` for bulk folder deletes |

There is **no dedicated `validate` command** in the public CLI. `akamas build` is the
closest thing to a schema check — malformed directories are expected to fail there.
This skill should therefore do its own structural validation (required fields, name
patterns, cross-references between component types and declared parameters/metrics)
before telling the user their pack is ready to build.
