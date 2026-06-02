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

If the system Python is externally managed, create a temporary virtual environment instead of forcing global installs:

```bash
python3 -m venv /tmp/captionforge-test-venv
/tmp/captionforge-test-venv/bin/python -m pip install -e '.[dev]'
/tmp/captionforge-test-venv/bin/python -m pytest -q
```

## High-Value CLI Examples

Start with a dry run before batch work:

```bash
captionforge batch ./videos -o ./out --dry-run
```

Batch burn bilingual subtitles by selecting both subtitle tracks:

```bash
captionforge batch ./videos -o ./out \
  --subtitle en \
  --subtitle zh \
  --multi-subtitle-layout stack \
  --yes
```

Use `--multi-subtitle-layout merge` when simultaneous subtitle text should be combined into one event separated by line breaks:

```bash
captionforge batch ./videos -o ./out \
  --subtitle en \
  --subtitle zh \
  --multi-subtitle-layout merge
```

Render modern rounded captions:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode rounded \
  --template rounded
```

Render a white rounded caption box with black text:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode rounded \
  --template rounded-white
```

Generate a rounded preview frame and exit before encoding:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode rounded \
  --template rounded \
  --preview-image preview \
  --preview-format auto \
  --preview-only
```

Embed soft subtitles instead of burning pixels:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --mode soft
```

## Performance And Encoding Notes

- `--encoder auto` is the default. It checks the selected ffmpeg build before choosing an encoder.
- Encoder preference is VideoToolbox on macOS, then NVENC, QSV, AMF, and CPU fallback.
- `--encoder cpu` forces software encoding.
- Platform aliases include `videotoolbox`, `nvenc`, `qsv`, and `amf`.
- Exact encoder names are accepted directly from ffmpeg, such as `libx264`, `libx265`, `libvpx-vp9`, `libsvtav1`, `libaom-av1`, `libvvenc`, `hevc_nvenc`, `av1_qsv`, or `prores_ks`.
- `--codec auto` follows known input videos when possible, including h264/hevc/av1/vp8/vp9/vvc. Use `--codec h264`, `--codec hevc`, `--codec av1`, `--codec vp9`, or `--codec vvc` to force output codec. `--codec h266` is an alias for `vvc`.
- Codec and encoder arguments are not limited to CaptionForge's examples. For unknown codecs, CaptionForge reads the current ffmpeg build's `-codecs` output and uses the encoder list advertised there. If multiple encoders exist and you want a specific one, pass the exact ffmpeg encoder with `--encoder`; use repeated `--ffmpeg-arg` for custom output options.
- H.266/VVC requires an ffmpeg build with `libvvenc`; it is treated as CPU software encoding and should be considered experimental for playback compatibility.
- Start batch GPU work with `--jobs 2`; higher values can make ffmpeg processes compete for CPU, GPU, and disk bandwidth.
- If automatic VideoToolbox encoding fails, CaptionForge retries with the CPU encoder for the same codec.
- Use `--quality ultra|high|medium|low` as the first tuning lever before adding raw `--ffmpeg-arg` overrides.

Common codec and encoder examples:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --encoder auto
captionforge burn movie.mp4 captions.srt -o out.mp4 --codec hevc --encoder nvenc
captionforge burn movie.mp4 captions.srt -o out.mp4 --codec av1 --encoder auto
captionforge burn movie.mp4 captions.srt -o out.webm --codec vp9 --encoder libvpx-vp9
captionforge burn movie.mp4 captions.srt -o out.mov --codec prores --encoder auto
captionforge burn movie.mp4 captions.srt -o out.mov --codec h266
captionforge burn movie.mp4 captions.srt -o out.mp4 --encoder libsvtav1
```

## Common Parameters

- `--render-mode ass` uses libass and preserves ASS-style subtitle behavior.
- `--render-mode rounded` draws subtitle overlays with Pillow and composites them with ffmpeg. Use it for real rounded boxes, padding, and modern caption cards.
- Rounded mode treats subtitle text as plain text plus line breaks; use ASS mode when advanced ASS inline styling must be preserved.
- `--template` accepts built-in templates such as `large`, `boxed`, `rounded`, and `rounded-white`, or a path to a JSON template.
- `--style-override` accepts a JSON object for one-off style changes, for example `--style-override '{"font_size": 60, "outline": 3}'`.
- `--font-dir` adds a directory for font discovery and libass font lookup.
- `--cjk-font` and `--latin-font` accept installed font family names, full names, or PostScript names.
- `--cjk-font-file` and `--latin-font-file` accept local TTF/OTF/TTC/OTC font files.
- Font files use family name by default. Use `--cjk-font-name-source full|postscript` or `--latin-font-name-source full|postscript` to select a specific face from the font name table.
- `captionforge font list`, `captionforge font search <query>`, and `captionforge font match <name>` show family, full name, PostScript name, file path, and source.
- Explicit fonts should fail fast when they do not exactly match family, full name, or PostScript name.
- `--font-rule` and `--font-rules` apply text-specific font overrides for keywords or character sets.
- `--output-res WIDTHxHEIGHT` forces output resolution; style sizing is scaled from `--reference-height`.
- `--keep-ass` writes the generated ASS file for inspection when diagnosing ASS rendering. It is available on `captionforge burn`.
- `--verbose-ffmpeg` is useful when debugging filter, encoder, or subtitle-rendering failures.

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
