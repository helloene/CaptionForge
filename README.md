# CaptionForge

[简体中文](README.zh-CN.md)

CaptionForge is a CLI for turning subtitle files into predictable video output. It can burn styled hard subtitles, embed soft subtitle tracks, batch-match videos and subtitles, and render modern rounded caption boxes that plain SRT cannot express.

It is designed for workflows that need precise subtitle styling and predictable video output:

- Transparent or semi-transparent subtitle backgrounds
- Different fonts for Chinese/CJK text and Latin letters inside the same subtitle line
- Reusable style templates
- Hard subtitles that look consistent across players
- Optional rounded caption boxes

## Features

- Hard subtitle burning through ffmpeg + libass
- Soft subtitle embedding for MP4/MOV-style outputs
- Input formats supported by `pysubs2`, including SRT, ASS/SSA, WebVTT, MicroDVD, MPL2, TMP, and JSON
- Automatic SRT/VTT/etc. to styled ASS conversion
- Separate CJK and Latin fonts in the same subtitle event
- Platform-aware default font fallback for macOS, Linux, and Windows
- Text-specific font override rules for keywords or character sets
- Transparent background by default
- Semi-transparent rectangular ASS boxes
- Rounded caption boxes via Pillow + ffmpeg overlay
- White rounded caption template for black text on a white pill-shaped box
- Built-in templates plus user JSON templates
- Font names or local TTF/OTF font files
- Automatic video resolution probing, `PlayResX/PlayResY` writing, and style scaling from a 1080p reference
- Quality presets for hard-burned output
- Batch matching, subtitle labels in output filenames, and multi-version exports
- Parallel batch jobs with whole-batch progress
- Automatic video frame-rate probing for rounded overlay sync
- Output pixel format preserved from source (fixes Windows player compatibility)
- HDR color metadata preservation (PQ/HLG)
- Event-driven VFR rendering for rounded mode (renders only on subtitle changes)
- Multi-threaded subtitle frame generation
- Progress bar with ETA for long renders
- Windows system font auto-discovery without fontconfig

## Install

```bash
python3 -m pip install -e .
```

For development:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

## Agent Skill

CaptionForge includes an agent skill at [`skills/captionforge-cli/SKILL.md`](skills/captionforge-cli/SKILL.md). It is a compact guide for agents to use and maintain the CLI without duplicating CLI behavior.

To fetch only the skill:

```bash
git clone --filter=blob:none --sparse https://github.com/helloene/CaptionForge.git captionforge-skill
cd captionforge-skill
git sparse-checkout set skills/captionforge-cli
```

## Requirements

CaptionForge requires `ffmpeg` and `ffprobe`.

For ASS hard subtitles, ffmpeg must include the `ass` or `subtitles` filter, which requires libass.

On macOS with Homebrew, the regular `ffmpeg` formula may not include libass. Install:

```bash
brew install ffmpeg-full
```

`ffmpeg-full` is keg-only. CaptionForge automatically checks common Homebrew paths such as `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` for hard subtitle rendering, so you do not need to replace your default `ffmpeg`.

On Windows, install an ffmpeg build that includes libass, then make sure `ffmpeg.exe` and `ffprobe.exe` are on `PATH`, or point CaptionForge to them with `CAPTIONFORGE_FFMPEG` and `CAPTIONFORGE_FFPROBE`.

You can also choose binaries explicitly:

```bash
CAPTIONFORGE_FFMPEG=/path/to/ffmpeg \
CAPTIONFORGE_FFPROBE=/path/to/ffprobe \
captionforge doctor
```

Check your environment:

```bash
captionforge doctor
```

## Choose A Workflow

Use this table first:

| Goal | Recommended command |
| --- | --- |
| Standard hard subtitles, best compatibility | `captionforge burn in.mp4 sub.srt -o out.mp4 --render-mode ass` |
| Modern rounded caption box | `captionforge burn in.mp4 sub.srt -o out.mp4 --render-mode rounded --template rounded` |
| White rounded caption box with black text | `captionforge burn in.mp4 sub.srt -o out.mp4 --render-mode rounded --template rounded-white` |
| Keep subtitles selectable in the player | `captionforge burn in.mp4 sub.srt -o out.mp4 --mode soft` |
| Batch a folder | `captionforge batch ./videos -o ./out --dry-run` |
| Generate styled ASS only | `captionforge ass sub.srt -o styled.ass --play-res 1920x1080` |

Mode notes:

- `ass` mode is fast and preserves more ASS subtitle behavior, but ASS boxes are rectangular.
- `rounded` mode draws text and boxes as graphics, so it can create real rounded boxes and padding.
- `soft` mode copies a subtitle track into the video container; player apps control how it looks.

## Quick Start

Burn normal hard subtitles:

```bash
captionforge burn input.mp4 subtitles.srt -o output.mp4 \
  --mode hard \
  --render-mode ass
```

Burn a white rounded caption box with black text:

```bash
captionforge burn input.mp4 subtitles.srt -o output.mp4 \
  --render-mode rounded \
  --template rounded-white
```

Embed a soft subtitle track:

```bash
captionforge burn input.mp4 subtitles.srt -o output.mp4 --mode soft
```

Batch burn every matching video/subtitle pair in a directory:

```bash
captionforge batch ./videos -o ./out --render-mode ass --dry-run
```

Remove `--dry-run` and add `--yes` when the plan looks right and you want unattended processing.

Generate styled ASS without rendering video:

```bash
captionforge ass subtitles.vtt -o styled.ass \
  --play-res 1920x1080
```

## Batch Workflows

Batch mode defaults to `--subtitle auto`. It matches subtitle names that equal the video stem or include the video stem as a filename field:

- `movie.mp4` + `movie.srt`
- `movie.mp4` + `movie.zh.srt`
- `movie.mp4` + `movie-zh-cn.srt`
- `movie.mp4` + `zh.movie.srt`
- `movie.mp4` + `ChineseMovie.srt`
- `movie.mp4` + `EnglishMovie.srt`
- `movie.mp4` + `en.srt` when the folder contains only one video

When running in an interactive terminal, batch mode prints the full plan and asks for confirmation before running ffmpeg. Use `--dry-run` to inspect matches and exit, or `--yes` for unattended execution.

If `auto` finds multiple subtitle candidates for the same video, an interactive terminal prompts you to choose by number or key. In non-interactive scripts, CaptionForge exits with an error and prints the choices so you can rerun with repeated `--subtitle`:

```bash
captionforge batch ./videos -o ./out --subtitle en --subtitle zh
```

Use `--recursive` to scan subdirectories and preserve their relative layout under the output directory.

### Output Names

Batch output filenames include subtitle labels by default, inferred from the matched subtitle filenames:

- `movie.mp4` + `movie.zh-cn.srt` -> `movie-captioned.zh-cn.mp4`
- `movie.mp4` + `movie.en.srt` + `movie.zh-cn.srt` -> `movie-captioned.en.zh-cn.mp4`

Label controls:

- `--subtitle-label-position suffix` writes `movie-captioned.zh-cn.mp4` (default)
- `--subtitle-label-position prefix` writes `zh-cn.movie-captioned.mp4`
- `--subtitle-label-position none` disables labels
- `--output-suffix "-subtitled"` changes the base suffix

### Multi-Version Exports

When you select more than one subtitle, the default is one combined output. To export separate language versions plus a bilingual version, use:

```bash
captionforge batch ./videos -o ./out \
  --subtitle en \
  --subtitle zh-cn \
  --subtitle-outputs both
```

This writes:

```text
movie-captioned.en.mp4
movie-captioned.zh-cn.mp4
movie-captioned.en.zh-cn.mp4
```

Use `--subtitle-outputs separate` when you only want the single-language files.

Soft subtitle batch mode can embed one subtitle file per output. If you use `--mode soft` with multiple selected subtitles, also use `--subtitle-outputs separate`.

With multiple ASS subtitles, `--multi-subtitle-layout stack` renders the first selected subtitle above the second. Use `merge` to combine active subtitle text in one subtitle event separated by line breaks:

```bash
captionforge batch ./videos -o ./out \
  --subtitle en \
  --subtitle zh \
  --multi-subtitle-layout merge
```

### Parallel Jobs And Progress

Batch processing runs one video at a time by default. Use `--jobs` to process multiple videos in parallel:

```bash
captionforge batch ./videos -o ./out --jobs 2
```

Start with `--jobs 2` for GPU encoding or large videos so ffmpeg processes do not compete too heavily for CPU, GPU, and disk bandwidth.

Progress is reported at two levels: rounded mode prints frame-rendering and encoding progress for each video, and batch mode prints completed outputs such as `3/10 complete`.

## Render Modes

### ASS Mode

`--render-mode ass` converts the input subtitle file to ASS and renders it with libass:

```bash
captionforge burn movie.mp4 captions.srt -o movie-captioned.mp4 \
  --render-mode ass \
  --background-alpha 255 \
  --outline 3
```

ASS mode supports standard ASS rendering and inline font switching. CaptionForge writes inline `{\fn...}` tags so CJK and Latin runs can use different fonts in the same subtitle line.

### Rounded Mode

`--render-mode rounded` draws subtitle overlays with Pillow, then composites them with ffmpeg:

```bash
captionforge burn movie.mp4 captions.srt -o movie-captioned.mp4 \
  --render-mode rounded \
  --template rounded \
  --corner-radius 18 \
  --padding-h 28 \
  --padding-v 16
```

Rounded mode supports real rounded boxes, padding, and mixed fonts. It treats subtitle text as plain text plus line breaks, so advanced ASS inline styling is not preserved. Use ASS mode when preserving ASS-specific styling matters.

Plain SRT files do not contain rounded-box styling. CaptionForge uses SRT timing and text, then draws the rounded caption box as a video overlay.

To check font fallback and box styling before spending time on a full encode, write one preview frame and stop. The preview is composited over the real video frame at the first active subtitle segment:

```bash
captionforge burn movie.mp4 captions.en.srt captions.zh-CN.srt -o out.mp4 \
  --render-mode rounded \
  --template rounded \
  --preview-image preview \
  --preview-format auto \
  --preview-only
```

Preview format `auto` writes PNG for SDR sources and AVIF for HDR sources. Use `--preview-format jxl` to request JPEG XL. If the selected HDR preview encoder is unavailable or fails, CaptionForge writes a PNG fallback instead.

For vertical video, move subtitles to the center height with ASS alignment:

```bash
--alignment 5
```

Common alignment values:

- `2`: bottom-center (default)
- `5`: middle-center, useful for vertical short video
- `8`: top-center

Rounded mode uses the same alignment values.

## Styles

Alpha values follow ASS convention:

- `0` means opaque
- `255` means fully transparent

Transparent subtitles:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --background-alpha 255 \
  --primary-color "#ffffff" \
  --outline-color "#000000"
```

Semi-transparent box in ASS mode:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode ass \
  --box \
  --background-color "#000000" \
  --background-alpha 140
```

Style fields can also be overridden with JSON:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --style-override '{"font_size": 60, "outline": 3, "background_alpha": 255}'
```

Hard subtitle rendering probes the input video size, writes `PlayResX/PlayResY`, and scales style values from a 1080p reference height. Change that basis with:

```bash
--reference-height 1080
```

By default, output resolution follows the input video. Force a larger output canvas and render subtitles at that resolution with:

```bash
--output-res 3840x2160
--output-res 7680x4320
```

## Templates

List built-in templates:

```bash
captionforge template list
```

Show a template:

```bash
captionforge template show rounded
```

Use a built-in template:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --template clean
```

White rounded subtitle box with black text:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode rounded \
  --template rounded-white
```

Export and edit a template:

```bash
captionforge template export rounded -o my-rounded.json
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode rounded \
  --template my-rounded.json
```

Template files can be a plain style object:

```json
{
  "font_size": 54,
  "background_alpha": 255,
  "outline": 2
}
```

Or an object with metadata:

```json
{
  "description": "My rounded subtitle style",
  "style": {
    "cjk_font": "PingFang SC",
    "latin_font": "Arial",
    "font_size": 54,
    "primary_color": "#ffffff",
    "outline_color": "#000000",
    "background_color": "#000000",
    "background_alpha": 110,
    "outline": 1,
    "margin_v": 48,
    "corner_radius": 20,
    "padding_h": 32,
    "padding_v": 18,
    "line_spacing": 10
  }
}
```

Precedence:

```text
defaults -> template -> explicit CLI style flags -> --style-override
```

For example:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --template large \
  --font-size 72
```

## Fonts

Inspect fonts from the CLI:

```bash
captionforge font list --limit 20
captionforge font search pingfang
captionforge font match "PingFang SC"
```

You can include your own font folder:

```bash
captionforge font search noto --font-dir ./fonts
```

Font discovery strategy:

- If `fc-list` / `fc-match` from fontconfig is available, CaptionForge uses it.
- On Windows, CaptionForge also scans `C:\\Windows\\Fonts` and `%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts`.
- On macOS, it scans system and user font directories such as `/System/Library/Fonts`, `/Library/Fonts`, and `~/Library/Fonts`.
- On Linux, it scans common font directories such as `/usr/share/fonts`, `/usr/local/share/fonts`, `~/.fonts`, and `~/.local/share/fonts`.
- Font family names are read from TTF/OTF/TTC files with `fontTools`.

When no font is specified, CaptionForge chooses installed defaults from a fallback list. Latin text is resolved separately from CJK text so English letters do not fall back to PingFang. The fallback order prefers macOS families first, then Linux/open font families, then Windows families:

- Latin: San Francisco-compatible names, Helvetica Neue, Lato/Inter/Noto Sans, Aptos/Segoe UI/Arial.
- CJK: PingFang SC/HK/TC, Hiragino, Apple SD Gothic Neo, Noto Sans CJK / Source Han Sans SC/HK/TC/JP/KR, Microsoft YaHei/JhengHei, Yu Gothic, Malgun Gothic.

If none of the preferred names are installed, CaptionForge uses a deterministic installed fallback font. The selected defaults are printed before rendering, for example:

```text
[CaptionForge] Selected default fonts: Latin=Helvetica Neue, CJK=PingFang SC
```

Use installed font family names:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --cjk-font "PingFang SC" \
  --latin-font "Arial"
```

Or local font files:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --cjk-font-file ./fonts/NotoSansSC-Regular.otf \
  --latin-font-file ./fonts/Inter-Regular.otf
```

ASS mode can also scan an extra font directory:

```bash
--font-dir ./fonts
```

### Font Override Rules

Use font rules when specific text should use a different font than the default Latin/CJK split:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --font-rule '{"font":"Display Sans","pattern":"keyword","mode":"contains-ignore-case"}'
```

Rules can also be stored in JSON:

```json
{
  "rules": [
    { "font": "Display Sans", "pattern": "keyword", "mode": "contains-ignore-case" },
    { "font": "Symbol Sans", "pattern": "mcd", "mode": "any-char-ignore-case" }
  ]
}
```

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --font-rules font-rules.json
```

Rule modes:

- `contains`: case-sensitive substring match
- `contains-ignore-case`: case-insensitive substring match
- `exact`: the whole text segment must match exactly
- `exact-ignore-case`: whole segment match, ignoring case
- `any-char`: match each character that appears in `pattern`
- `any-char-ignore-case`: character-set match, ignoring case

## Quality Presets

Hard subtitle output supports:

- `--quality ultra`: CRF 18, slow
- `--quality high`: CRF 23, medium
- `--quality medium`: CRF 28, medium
- `--quality low`: CRF 32, fast

Example:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --quality high
```

## GPU Encoding

CaptionForge can automatically use hardware encoders when available:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --encoder auto
```

`--encoder auto` always checks the selected ffmpeg build before choosing an encoder. If the platform encoder for the selected codec is not exposed by ffmpeg, CaptionForge skips it and tries the next GPU family, then CPU.

Encoder options:

- `--encoder auto` (default): pick the best available encoder in order: VideoToolbox on macOS, then NVENC > QSV > AMF > CPU
- `--encoder cpu`: force a software encoder for the selected codec
- `--encoder videotoolbox`: Apple VideoToolbox (`h264_videotoolbox` or `hevc_videotoolbox`)
- `--encoder nvenc`: NVIDIA NVENC (`h264_nvenc`, `hevc_nvenc`, or `av1_nvenc`)
- `--encoder qsv`: Intel Quick Sync (`h264_qsv`, `hevc_qsv`, or `av1_qsv`)
- `--encoder amf`: AMD AMF (`h264_amf`, `hevc_amf`, or `av1_amf`)
- Exact encoder names such as `libx264`, `libx265`, `libsvtav1`, `libaom-av1`, `hevc_nvenc`, or `av1_qsv`

By default, `--codec auto` follows h264/hevc/av1 input videos when possible. Choose the output video codec separately when you want to transcode:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --codec hevc --encoder nvenc
captionforge burn movie.mp4 captions.srt -o out.mp4 --codec av1 --encoder auto
captionforge burn movie.mp4 captions.srt -o out.mp4 --encoder libsvtav1
```

GPU encoding is applied to both ASS and rounded render modes. If automatic VideoToolbox encoding fails, CaptionForge retries with the CPU encoder for the same codec. Quality presets map to the encoder-specific parameters (VideoToolbox qscale, CQ for NVENC, global_quality for QSV, CQP for AMF).

AV1 follows the same auto-selection rules:

- On NVIDIA systems, `av1_nvenc` is used when ffmpeg provides it.
- On Intel systems, `av1_qsv` is used when ffmpeg provides it.
- On AMD systems, `av1_amf` is used when ffmpeg provides it.
- On Apple Silicon, AV1 VideoToolbox encoding is normally unavailable, so CaptionForge skips VideoToolbox for AV1 and falls back to another available GPU encoder or CPU (`libsvtav1`, then `libaom-av1`).

## HDR Subtitle Brightness

When the source video uses HDR PQ (`smpte2084`) or HLG (`arib-std-b67`), CaptionForge automatically dims subtitle colors so they don't blow out on HDR displays:

- **PQ**: subtitle colors scaled to ~50% (maps SDR white to ~100 nits in PQ space)
- **HLG**: subtitle colors scaled to ~75% (HLG has a smaller brightness headroom)

Color primaries and transfer metadata are also preserved in the output file so players correctly trigger HDR mode.

## Troubleshooting

Show ffmpeg logs:

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --verbose-ffmpeg
```

If hard ASS rendering fails, run:

```bash
captionforge doctor
```

You should see `ass filter: yes` or `subtitles filter: yes`.

If fonts do not render as expected, verify the font name with your system font manager or use explicit font files with `--cjk-font-file` and `--latin-font-file`.

## Notes

- ASS mode is best for standard subtitle rendering and ASS compatibility.
- Rounded mode is best for modern rounded backgrounds and simple subtitle text.
- Soft subtitle mode does not apply style settings because the player controls rendering.
