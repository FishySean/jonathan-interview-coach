# Jonathan Interview Coach — Skill

Distilled interview coaching knowledge from [MrJonathanCareer](https://www.youtube.com/@MrJonathanCareer) YouTube Shorts — packaged in **Agent Skills** layout (lean entry + progressive disclosure).

**Repository:** [FishySean/jonathan-interview-coach](https://github.com/FishySean/jonathan-interview-coach)

## Layout

| Path | Purpose |
|------|---------|
| `SKILL.md` | Short entrypoint (YAML frontmatter, role, coaching loop, index) — keep lean |
| `references/frameworks.md` | Named frameworks quick lookup |
| `references/by_video/*.md` | Per-Short distillations (open on demand) |
| `README.md` | This file |
| `CHANGELOG.md` | Version history |

This matches the [Agent Skills](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills) pattern: **SKILL.md stays short**; details live under `references/` so the model loads them only when needed.

## Quick start — Claude Code / Cursor skill

```bash
mkdir -p .claude/skills/jonathan-interview-coach
cp -R data/skill/SKILL.md data/skill/references \
  .claude/skills/jonathan-interview-coach/
```

Or symlink the whole folder:

```bash
ln -s "$(pwd)/data/skill" .claude/skills/jonathan-interview-coach
```

## Claude Project (Knowledge)

Projects work best with fewer large dumps. Prefer:

1. Upload **`SKILL.md`** + **`references/frameworks.md`**
2. Upload individual `references/by_video/*.md` only for topics you care about

Or zip the whole `data/skill/` folder if your workflow supports a skill directory.

Project instructions:

```
You are a Jonathan-style interview coach. Use the skill / knowledge only when
I ask for mock interviews, interview prep, or say 「Jonathan 模式」.
Open references/by_video only when you need a specific Short’s verbatim script.
```

## Updating

```bash
python -m scripts.distill --merge-only
```

Rebuilds lean `SKILL.md`, syncs `references/by_video/` from `data/distilled/by_video/`, refreshes `frameworks.md`.

See `CHANGELOG.md` for version history.

## Disclaimer

Video content © original creators. This skill contains **transformed notes** for personal learning and interview prep — not a redistribution of videos or transcripts.
