# Akamas Claude Code Plugins

A monorepo of [Claude Code](https://docs.claude.com/en/docs/claude-code) plugins for
Akamas optimization-pack engineering. Each plugin lives in its own folder under
`plugins/`, is independently versioned, and can be installed on its own. This repo
itself is not an optimization pack — it's tooling that helps engineers create and
maintain Akamas optimization pack repositories (like `optimization-packs/vllm`).

## Plugins

- **[akamas-optimization-pack](plugins/akamas-optimization-pack/README.md)** — scaffold new Akamas optimization packs and safely modify existing ones.
- **[akamas-study-manager](plugins/akamas-study-manager/README.md)** — scaffold new Akamas studies (system, components, telemetry, workflow, study manifest) and safely modify existing ones.

## Installing from this repo

Add this repo as a plugin marketplace, then install a plugin from it:

```
/plugin marketplace add akamaslabs/akamas-claude-plugins
/plugin install akamas-optimization-pack
```

## Testing a plugin locally

Before a plugin change is merged or published, you can try it directly from any target
repo without installing it, by pointing `claude` at the plugin's folder:

```
claude --plugin-dir /path/to/akamas-claude-plugins/plugins/akamas-optimization-pack
```

## Adding a new plugin

New plugins follow the same internal shape (`.claude-plugin/plugin.json`, `skills/`,
`README.md`) under their own `plugins/<plugin-name>/` folder, plus one new entry
appended to `.claude-plugin/marketplace.json`. See [CLAUDE.md](CLAUDE.md) §1 (monorepo
layout) and §2.1 (marketplace manifest) for the exact convention.
