# Jonathan Interview Coach — Skill

Distilled interview coaching knowledge from [MrJonathanCareer](https://www.youtube.com/@MrJonathanCareer) YouTube Shorts — formatted for Claude.

**Repository:** [FishySean/jonathan-interview-coach](https://github.com/FishySean/jonathan-interview-coach)

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | **The skill itself** — upload to Claude or load as a skill |
| `README.md` | This file — how to install and use |
| `CHANGELOG.md` | What's included in each version |

## Quick start — Claude Project (recommended)

1. Open [Claude](https://claude.ai) → **Projects** → **New Project**
2. Name it e.g. `Interview Coach`
3. **Add Knowledge** → upload `data/skill/SKILL.md`
4. In Project instructions, add:

   ```
   You are a Jonathan-style interview coach. Use the uploaded knowledge only when
   I ask for mock interviews, interview prep, or say 「Jonathan 模式」.
   ```

5. Use this Project **only for interview practice** — not daily chat.

## Claude Code / `.claude/skills/` (optional)

```bash
mkdir -p .claude/skills/jonathan-interview-coach
cp data/skill/SKILL.md .claude/skills/jonathan-interview-coach/SKILL.md
```

## What's inside `SKILL.md`

Each covered Short contributes:

- Core principles & interview philosophy
- Evaluation criteria & common mistakes
- Follow-up questions & answer frameworks
- **Good vs bad examples** (Jonathan's teaching style)
- **Sample answers (verbatim)** — templates and full coached scripts

## Updating

```bash
python -m scripts.distill --merge-only
```

See `CHANGELOG.md` for version history.

## Disclaimer

Video content © original creators. This skill contains **transformed notes** for personal learning and interview prep — not a redistribution of videos or transcripts.
