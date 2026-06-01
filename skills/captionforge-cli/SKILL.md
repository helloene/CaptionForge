---
name: captionforge-cli
description: Use when working on CaptionForge, a Python CLI for subtitle conversion, hard and soft subtitle rendering, rounded captions, ffmpeg integration, fonts, templates, and batch video workflows.
---

# CaptionForge CLI

CaptionForge is a Python CLI project. The application code lives in `src/captionforge/`, and the console entry point is defined in `pyproject.toml` as `captionforge = "captionforge.cli:main"`.

## Principles

- Treat the CLI as the source of truth. Do not duplicate CLI behavior in temporary scripts unless investigation requires it.
- Discover current behavior with `captionforge --help` and `captionforge <command> --help`.
- Prefer focused changes in `src/captionforge/` and matching tests in `tests/`.
- Keep generated videos, demo media, caches, virtual environments, and local outputs out of the repository.

## Common Workflow

1. Inspect `pyproject.toml` and the relevant module under `src/captionforge/`.
2. Use CLI help output to confirm command names and options.
3. Make the smallest relevant source change.
4. Add or update focused tests under `tests/`.
5. Run:

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
```

## Project Map

- `src/captionforge/cli.py`: command-line interface and command wiring.
- `src/captionforge/ffmpeg.py`: ffmpeg and ffprobe integration.
- `src/captionforge/subtitles.py`: subtitle parsing and conversion behavior.
- `src/captionforge/styles.py`: subtitle style handling.
- `src/captionforge/templates.py`: built-in style templates.
- `src/captionforge/fonts.py` and `src/captionforge/fontsplit.py`: font discovery and mixed-script font handling.
- `src/captionforge/rounded.py`: rounded caption rendering.
- `tests/`: regression tests for CLI behavior and core modules.

## Using This Skill

This skill is stored inside the CaptionForge repository so it can travel with the project and remain useful to different agents.

For local Codex use, symlink it into the Codex skills directory:

```bash
mkdir -p ~/.codex/skills
ln -s /path/to/CaptionForge/skills/captionforge-cli ~/.codex/skills/captionforge-cli
```

To fetch only this skill from the remote CaptionForge repository, use Git sparse checkout:

```bash
git clone --filter=blob:none --sparse https://github.com/helloene/CaptionForge.git captionforge-skill
cd captionforge-skill
git sparse-checkout set skills/captionforge-cli
```

Then symlink the checked-out skill:

```bash
mkdir -p ~/.codex/skills
ln -s "$PWD/skills/captionforge-cli" ~/.codex/skills/captionforge-cli
```

Sparse checkout still uses the CaptionForge repository; it only keeps the selected skill directory visible in the working tree.
