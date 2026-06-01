# CaptionForge

[English](README.md)

CaptionForge 是一个命令行字幕工具，用于把字幕文件稳定地变成视频输出。它可以烧录带样式的硬字幕、嵌入软字幕轨、批量匹配视频和字幕，也可以渲染普通 SRT 无法表达的现代圆角字幕框。

它面向需要精细控制字幕样式和稳定视频输出的场景：

- 字幕背景透明或半透明
- 同一句字幕里中文/CJK 和英文字母使用不同字体
- 可复用的字幕样式模板
- 烧录后在不同播放器里保持一致效果
- 可选圆角字幕框

## 功能

- 通过 ffmpeg + libass 烧录硬字幕
- 为 MP4/MOV 等输出嵌入软字幕轨
- 支持 `pysubs2` 可读取的字幕格式，包括 SRT、ASS/SSA、WebVTT、MicroDVD、MPL2、TMP 和 JSON
- 自动把 SRT/VTT 等字幕转换为带样式的 ASS
- 同一条字幕事件中支持中文/CJK 与 Latin 字符分字体渲染
- 根据 macOS、Linux、Windows 自动选择默认字体 fallback
- 支持按关键词或字符集合覆写特定文本字体
- 默认透明背景
- 支持 ASS 半透明矩形字幕框
- 支持 Pillow + ffmpeg overlay 的真实圆角字幕框
- 内置白底黑字圆角字幕框模板
- 内置模板，也支持用户自定义 JSON 模板
- 支持字体名称或本地 TTF/OTF 字体文件
- 自动探测视频分辨率，写入 `PlayResX/PlayResY`，并按 1080p 参考高度缩放样式
- 硬字幕输出支持质量预设
- 批量匹配字幕，输出文件名自动带字幕标签，并支持多版本导出
- 批量任务支持并发处理和整体进度
- 圆角模式自动探测视频帧率以同步 overlay
- 输出保留源视频像素格式，提升 Windows 播放兼容性
- 保留 HDR 色彩元数据，并针对 PQ/HLG 自动降低字幕亮度
- 圆角模式按字幕事件变化渲染 VFR overlay，减少无效帧
- 多线程生成字幕帧
- 长任务显示进度和 ETA
- Windows 无 fontconfig 时也会自动发现系统字体

## 安装

```bash
python3 -m pip install -e .
```

开发环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

## Agent Skill

CaptionForge 内置了一个 agent skill：[`skills/captionforge-cli/SKILL.md`](skills/captionforge-cli/SKILL.md)。它是给 agent 使用和维护 CLI 的简短指南，不复制 CLI 的完整行为。

只拉取这个 skill 可以使用 Git sparse checkout：

```bash
git clone --filter=blob:none --sparse https://github.com/helloene/CaptionForge.git captionforge-skill
cd captionforge-skill
git sparse-checkout set skills/captionforge-cli
```

## 环境要求

CaptionForge 需要 `ffmpeg` 和 `ffprobe`。

ASS 硬字幕渲染要求 ffmpeg 包含 `ass` 或 `subtitles` 滤镜，也就是需要启用 libass。

macOS + Homebrew 环境下，普通 `ffmpeg` formula 可能不包含 libass。建议安装：

```bash
brew install ffmpeg-full
```

`ffmpeg-full` 是 keg-only，不会自动替换系统里的默认 `ffmpeg`。CaptionForge 会自动检查常见 Homebrew 路径，例如 `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`，因此通常不需要手动替换默认 ffmpeg。

Windows 上请安装包含 libass 的 ffmpeg 构建，并确保 `ffmpeg.exe` 和 `ffprobe.exe` 在 `PATH` 中；也可以通过 `CAPTIONFORGE_FFMPEG` 和 `CAPTIONFORGE_FFPROBE` 显式指定路径。

也可以显式指定二进制路径：

```bash
CAPTIONFORGE_FFMPEG=/path/to/ffmpeg \
CAPTIONFORGE_FFPROBE=/path/to/ffprobe \
captionforge doctor
```

检查当前环境：

```bash
captionforge doctor
```

## 选择工作流

先从这张表选命令：

| 目标 | 推荐命令 |
| --- | --- |
| 标准硬字幕，兼容性最好 | `captionforge burn in.mp4 sub.srt -o out.mp4 --render-mode ass` |
| 现代圆角字幕框 | `captionforge burn in.mp4 sub.srt -o out.mp4 --render-mode rounded --template rounded` |
| 白底黑字圆角字幕框 | `captionforge burn in.mp4 sub.srt -o out.mp4 --render-mode rounded --template rounded-white` |
| 保留播放器可选字幕轨 | `captionforge burn in.mp4 sub.srt -o out.mp4 --mode soft` |
| 批量处理目录 | `captionforge batch ./videos -o ./out --dry-run` |
| 只生成带样式的 ASS 文件 | `captionforge ass sub.srt -o styled.ass --play-res 1920x1080` |

模式说明：

- `ass` 模式速度快，也更适合保留 ASS 字幕行为，但字幕框是矩形。
- `rounded` 模式会把文字和背景框画成图形，因此可以做真实圆角、padding 和现代字幕框。
- `soft` 模式只把字幕轨嵌入视频容器，最终样式由播放器决定。

## 快速开始

烧录普通硬字幕：

```bash
captionforge burn input.mp4 subtitles.srt -o output.mp4 \
  --mode hard \
  --render-mode ass
```

烧录白底黑字圆角字幕框：

```bash
captionforge burn input.mp4 subtitles.srt -o output.mp4 \
  --render-mode rounded \
  --template rounded-white
```

嵌入软字幕轨：

```bash
captionforge burn input.mp4 subtitles.srt -o output.mp4 --mode soft
```

批量处理目录里的视频和字幕：

```bash
captionforge batch ./videos -o ./out --render-mode ass --dry-run
```

确认计划无误后，去掉 `--dry-run`；如果要无人值守运行，再加 `--yes`。

只生成带样式的 ASS 文件，不渲染视频：

```bash
captionforge ass subtitles.vtt -o styled.ass \
  --play-res 1920x1080
```

## 批量工作流

批量模式默认使用 `--subtitle auto`。它会匹配与视频同名的字幕，也会匹配文件名字段中包含视频名的字幕：

- `movie.mp4` + `movie.srt`
- `movie.mp4` + `movie.zh.srt`
- `movie.mp4` + `movie-zh-cn.srt`
- `movie.mp4` + `zh.movie.srt`
- `movie.mp4` + `中文Movie.srt`
- `movie.mp4` + `EnglishMovie.srt`
- 当目录里只有一个视频时，`movie.mp4` + `en.srt`

在交互式终端里，批量模式会先打印完整执行计划，并询问是否继续运行 ffmpeg。只想查看匹配结果时用 `--dry-run`，需要无人值守静默执行时用 `--yes`。

如果 `auto` 为同一个视频找到多个字幕候选，交互式终端会让你直接输入编号或 key 选择；在非交互脚本里，CaptionForge 会退出并打印候选列表。也可以重新运行命令，用重复的 `--subtitle` 明确选择一个或多个字幕：

```bash
captionforge batch ./videos -o ./out --subtitle en --subtitle zh
```

需要递归扫描子目录时使用 `--recursive`，输出目录会保留相对目录结构。

### 输出文件名

批量输出文件名默认会带字幕标签，标签从字幕文件名里识别：

- `movie.mp4` + `movie.zh-cn.srt` -> `movie-captioned.zh-cn.mp4`
- `movie.mp4` + `movie.en.srt` + `movie.zh-cn.srt` -> `movie-captioned.en.zh-cn.mp4`

文件名相关选项：

- `--subtitle-label-position suffix`：写成 `movie-captioned.zh-cn.mp4`，默认值
- `--subtitle-label-position prefix`：写成 `zh-cn.movie-captioned.mp4`
- `--subtitle-label-position none`：关闭字幕标签
- `--output-suffix "-subtitled"`：修改基础输出后缀

### 多版本导出

如果想同时导出英文版、中文版和双语版：

```bash
captionforge batch ./videos -o ./out \
  --subtitle en \
  --subtitle zh-cn \
  --subtitle-outputs both
```

这会写出：

```text
movie-captioned.en.mp4
movie-captioned.zh-cn.mp4
movie-captioned.en.zh-cn.mp4
```

如果只想要单语文件，用 `--subtitle-outputs separate`。

软字幕批量模式每个输出只能嵌入一个字幕文件。如果 `--mode soft` 同时选择多个字幕，请配合 `--subtitle-outputs separate` 使用。

多个 ASS 字幕默认使用 `--multi-subtitle-layout stack`，第一个字幕显示在上方，第二个显示在下方。使用 `merge` 可以把同时激活的字幕合并到同一个字幕事件里，用换行分隔：

```bash
captionforge batch ./videos -o ./out \
  --subtitle en \
  --subtitle zh \
  --multi-subtitle-layout merge
```

### 并发和进度

批量模式默认一次处理一个视频。可以用 `--jobs` 同时处理多个视频：

```bash
captionforge batch ./videos -o ./out --jobs 2
```

如果使用 GPU 编码或处理大视频，建议先从 `--jobs 2` 开始，避免多个 ffmpeg 进程过度争抢 CPU、GPU 和磁盘。

进度分两层显示：圆角模式会显示单个视频的字幕帧渲染和编码进度；批量模式会显示整体完成进度，例如 `3/10 complete`。

## 渲染模式

### ASS 模式

`--render-mode ass` 会把输入字幕转换为 ASS，并通过 libass 渲染：

```bash
captionforge burn movie.mp4 captions.srt -o movie-captioned.mp4 \
  --render-mode ass \
  --background-alpha 255 \
  --outline 3
```

ASS 模式适合标准字幕渲染，也支持行内字体切换。CaptionForge 会写入 `{\fn...}` 标签，让同一句字幕里的 CJK 和 Latin 字符使用不同字体。

### 圆角模式

`--render-mode rounded` 会用 Pillow 绘制字幕透明层，再用 ffmpeg 合成到视频：

```bash
captionforge burn movie.mp4 captions.srt -o movie-captioned.mp4 \
  --render-mode rounded \
  --template rounded \
  --corner-radius 18 \
  --padding-h 28 \
  --padding-v 16
```

圆角模式支持真实圆角框、padding 和混合字体。它会把字幕当作纯文本加换行处理，不保留复杂 ASS 行内样式。需要保留 ASS 高级样式时，请使用 ASS 模式。

普通 SRT 文件本身不包含圆角框样式。CaptionForge 会使用 SRT 的时间轴和文本，再把圆角字幕框作为视频 overlay 绘制出来。

为了避免完整编码后才发现字体回退或方块字，可以先生成一张字幕效果预览图并停止。预览图会取第一段有效字幕所在的视频帧，并把字幕真实合成到画面上：

```bash
captionforge burn movie.mp4 captions.en.srt captions.zh-CN.srt -o out.mp4 \
  --render-mode rounded \
  --template rounded \
  --preview-image preview \
  --preview-format auto \
  --preview-only
```

预览格式 `auto` 会在 SDR 源上写 PNG，在 HDR 源上写 AVIF。需要 JPEG XL 时可手动使用 `--preview-format jxl`。如果所选 HDR 预览编码器不可用或编码失败，CaptionForge 会回退写出 PNG。

竖屏视频可以用 ASS 对齐值把字幕放到画面中间高度：

```bash
--alignment 5
```

常用对齐值：

- `2`：底部居中，默认值
- `5`：中间居中，适合竖屏短视频
- `8`：顶部居中

圆角模式也使用同一套对齐值。

## 样式

Alpha 值沿用 ASS 习惯：

- `0` 表示不透明
- `255` 表示完全透明

透明背景字幕：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --background-alpha 255 \
  --primary-color "#ffffff" \
  --outline-color "#000000"
```

ASS 模式下的半透明矩形框：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode ass \
  --box \
  --background-color "#000000" \
  --background-alpha 140
```

也可以用 JSON 覆盖样式字段：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --style-override '{"font_size": 60, "outline": 3, "background_alpha": 255}'
```

硬字幕渲染会自动探测输入视频尺寸，写入 `PlayResX/PlayResY`，并以 1080p 为参考高度缩放样式。可以这样修改参考高度：

```bash
--reference-height 1080
```

默认输出分辨率跟随输入视频。可以强制放大输出画布，并按该分辨率渲染字幕：

```bash
--output-res 3840x2160
--output-res 7680x4320
```

## 模板

列出内置模板：

```bash
captionforge template list
```

查看模板内容：

```bash
captionforge template show rounded
```

使用内置模板：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --template clean
```

白底黑字圆角字幕框：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode rounded \
  --template rounded-white
```

导出模板后自行编辑：

```bash
captionforge template export rounded -o my-rounded.json
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --render-mode rounded \
  --template my-rounded.json
```

模板文件可以是普通样式对象：

```json
{
  "font_size": 54,
  "background_alpha": 255,
  "outline": 2
}
```

也可以包含描述信息：

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

样式优先级：

```text
默认值 -> 模板 -> 显式 CLI 样式参数 -> --style-override
```

例如：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --template large \
  --font-size 72
```

## 字体

可以用 CLI 检查字体：

```bash
captionforge font list --limit 20
captionforge font search pingfang
captionforge font match "PingFang SC"
```

也可以额外搜索自己的字体目录：

```bash
captionforge font search noto --font-dir ./fonts
```

字体发现策略：

- 如果系统中有 fontconfig 的 `fc-list` / `fc-match`，优先使用它们。
- Windows 会额外扫描 `C:\\Windows\\Fonts` 和 `%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts`。
- macOS 会扫描 `/System/Library/Fonts`、`/Library/Fonts`、`~/Library/Fonts` 等系统和用户字体目录。
- Linux 会扫描 `/usr/share/fonts`、`/usr/local/share/fonts`、`~/.fonts`、`~/.local/share/fonts` 等常见目录。
- 字体 family name 会通过 `fontTools` 从 TTF/OTF/TTC 文件中读取。

如果没有显式指定字体，CaptionForge 会从已安装字体里按 fallback 列表选择默认值。Latin 和 CJK 会分开选择，避免英文字母落到苹方这类中文字体上。fallback 顺序优先 macOS 字体，然后是 Linux/开源字体，最后是 Windows 字体：

- Latin：San Francisco 兼容名称、Helvetica Neue、Lato/Inter/Noto Sans、Aptos/Segoe UI/Arial。
- CJK：PingFang SC/HK/TC、Hiragino、Apple SD Gothic Neo、Noto Sans CJK / Source Han Sans SC/HK/TC/JP/KR、Microsoft YaHei/JhengHei、Yu Gothic、Malgun Gothic。

如果候选列表都没有命中，CaptionForge 会确定性地选择一个已安装字体兜底。最终选择的默认字体会在渲染前输出，例如：

```text
[CaptionForge] Selected default fonts: Latin=Helvetica Neue, CJK=PingFang SC
```

使用系统已安装的字体名称：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --cjk-font "PingFang SC" \
  --latin-font "Arial"
```

或使用本地字体文件：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --cjk-font-file ./fonts/NotoSansSC-Regular.otf \
  --latin-font-file ./fonts/Inter-Regular.otf
```

ASS 模式还可以额外扫描字体目录：

```bash
--font-dir ./fonts
```

### 字体覆写规则

如果某些特定文本需要使用不同于默认 Latin/CJK 分流的字体，可以使用字体规则：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 \
  --font-rule '{"font":"Display Sans","pattern":"keyword","mode":"contains-ignore-case"}'
```

规则也可以放在 JSON 文件中：

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

匹配模式：

- `contains`：区分大小写的包含匹配
- `contains-ignore-case`：忽略大小写的包含匹配
- `exact`：整段文本严格匹配
- `exact-ignore-case`：整段文本匹配，忽略大小写
- `any-char`：匹配 `pattern` 中出现的任意字符
- `any-char-ignore-case`：忽略大小写的任意字符匹配

## 质量预设

硬字幕输出支持：

- `--quality ultra`：CRF 18，slow
- `--quality high`：CRF 23，medium
- `--quality medium`：CRF 28，medium
- `--quality low`：CRF 32，fast

示例：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --quality high
```

## GPU / HEVC / AV1 编码

CaptionForge 可以自动使用可用的硬件编码器：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --encoder auto
```

`--encoder auto` 会先检查当前 ffmpeg 是否真的提供对应 encoder。某个平台不支持所选 codec 时，CaptionForge 会跳过它，继续尝试下一个 GPU 系列，最后回退到 CPU。

编码器选项：

- `--encoder auto`（默认）：macOS 优先选择 VideoToolbox，然后按 NVENC > QSV > AMF > CPU 的顺序自动选择
- `--encoder cpu`：为所选 codec 强制使用软件编码器
- `--encoder videotoolbox`：Apple VideoToolbox（`h264_videotoolbox` 或 `hevc_videotoolbox`）
- `--encoder nvenc`：NVIDIA NVENC（`h264_nvenc`、`hevc_nvenc` 或 `av1_nvenc`）
- `--encoder qsv`：Intel Quick Sync（`h264_qsv`、`hevc_qsv` 或 `av1_qsv`）
- `--encoder amf`：AMD AMF（`h264_amf`、`hevc_amf` 或 `av1_amf`）
- 也可以直接指定精确编码器，例如 `libx264`、`libx265`、`libsvtav1`、`libaom-av1`、`hevc_nvenc`、`av1_qsv`

默认 `--codec auto` 会尽量跟随输入视频的 h264/hevc/av1 codec。需要转码时也可以单独指定输出 codec：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --codec hevc --encoder nvenc
captionforge burn movie.mp4 captions.srt -o out.mp4 --codec av1 --encoder auto
captionforge burn movie.mp4 captions.srt -o out.mp4 --encoder libsvtav1
```

GPU 编码同时适用于 ASS 和 rounded 两种硬字幕渲染模式。如果自动选择的 VideoToolbox 编码失败，CaptionForge 会用同 codec 的 CPU 编码器重试。质量预设会映射到对应编码器参数，例如 VideoToolbox 使用 qscale，NVENC 使用 CQ，QSV 使用 global_quality，AMF 使用 CQP。

AV1 也遵循同样的自动选择规则：

- NVIDIA 机器上，如果 ffmpeg 提供 `av1_nvenc`，会自动使用。
- Intel 机器上，如果 ffmpeg 提供 `av1_qsv`，会自动使用。
- AMD 机器上，如果 ffmpeg 提供 `av1_amf`，会自动使用。
- Apple Silicon 通常没有 AV1 VideoToolbox 硬件编码器，所以 AV1 会跳过 VideoToolbox，继续尝试其他可用 GPU encoder，最后回退到 CPU（优先 `libsvtav1`，其次 `libaom-av1`）。

## 故障排查

显示 ffmpeg 日志：

```bash
captionforge burn movie.mp4 captions.srt -o out.mp4 --verbose-ffmpeg
```

如果 ASS 硬字幕渲染失败，先运行：

```bash
captionforge doctor
```

正常情况下应该看到 `ass filter: yes` 或 `subtitles filter: yes`。

如果字体渲染不符合预期，先用系统字体管理器确认字体名称，或直接使用 `--cjk-font-file` 和 `--latin-font-file` 指定字体文件。

## 说明

- ASS 模式适合标准字幕渲染和 ASS 兼容性。
- 圆角模式适合现代圆角背景和简单字幕文本。
- 软字幕模式不会应用样式设置，因为最终渲染由播放器控制。
