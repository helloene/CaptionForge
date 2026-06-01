from argparse import Namespace

import pytest

from captionforge.cli import (
    AmbiguousSubtitleError,
    DEFAULT_SUBTITLE_TAGS,
    batch_output_path,
    build_parser,
    find_batch_matches,
    find_batch_pairs,
    ass_font_dirs,
    parse_play_res,
    resolve_codec,
    burn_one,
    run_batch_jobs,
    style_from_args,
    subtitle_match_score,
    print_selected_default_fonts,
    load_font_rules,
    BatchMatch,
    batch_outputs_for_match,
    batch_outputs_for_matches,
    validate_batch_outputs,
    subtitle_label_for_video,
)


def base_args(**kwargs):
    values = {
        "cjk_font": None,
        "latin_font": None,
        "cjk_font_file": None,
        "latin_font_file": None,
        "font_size": None,
        "primary_color": None,
        "outline_color": None,
        "background_color": None,
        "primary_alpha": None,
        "outline_alpha": None,
        "background_alpha": None,
        "outline": None,
        "shadow": None,
        "margin_v": None,
        "margin_l": None,
        "margin_r": None,
        "alignment": None,
        "box": None,
        "corner_radius": None,
        "padding_h": None,
        "padding_v": None,
        "line_spacing": None,
        "style_override": None,
        "template": None,
    }
    values.update(kwargs)
    return Namespace(**values)


def test_style_override_updates_fields():
    style = style_from_args(base_args(style_override='{"font_size": 60, "boxed": true}'))
    assert style.font_size == 60
    assert style.boxed is True


def test_template_applies_before_override():
    style = style_from_args(base_args(template="large", style_override='{"font_size": 70}'))
    assert style.font_size == 70
    assert style.outline == 3.0


def test_cli_style_arg_overrides_template():
    style = style_from_args(base_args(template="large", font_size=72))
    assert style.font_size == 72
    assert style.outline == 3.0


def test_style_uses_platform_default_fonts(monkeypatch):
    monkeypatch.setattr("captionforge.cli.default_font", lambda role, extra_dirs=None: "SF Pro Text" if role == "latin" else "PingFang SC")

    style = style_from_args(base_args(font_dir=[]))

    assert style.latin_font == "SF Pro Text"
    assert style.cjk_font == "PingFang SC"


def test_style_explicit_fonts_override_platform_defaults(monkeypatch):
    monkeypatch.setattr("captionforge.cli.default_font", lambda role, extra_dirs=None: "ignored")

    style = style_from_args(base_args(cjk_font="Noto Sans CJK SC", latin_font="Lato", font_dir=[]))

    assert style.cjk_font == "Noto Sans CJK SC"
    assert style.latin_font == "Lato"


def test_print_selected_default_fonts_reports_only_implicit_fonts(capsys):
    print_selected_default_fonts(
        base_args(cjk_font=None, latin_font="Lato", cjk_font_file=None, latin_font_file=None),
        style_from_args(base_args(cjk_font="PingFang SC", latin_font="Lato", font_dir=[])),
    )

    captured = capsys.readouterr()
    assert "CJK=PingFang SC" in captured.err
    assert "Latin=" not in captured.err


def test_load_font_rules_reads_inline_and_file(tmp_path):
    rules_path = tmp_path / "font-rules.json"
    rules_path.write_text('{"rules": [{"font": "FileFont", "pattern": "beta", "mode": "contains"}]}', encoding="utf-8")
    args = base_args(
        font_rule=['{"font": "InlineFont", "pattern": "alpha", "mode": "contains-ignore-case"}'],
        font_rules=rules_path,
    )

    rules = load_font_rules(args)

    assert [(rule.font, rule.pattern, rule.mode) for rule in rules] == [
        ("InlineFont", "alpha", "contains-ignore-case"),
        ("FileFont", "beta", "contains"),
    ]


def test_cjk_font_file_sets_style_family(monkeypatch, tmp_path):
    font_file = tmp_path / "CustomCJK.otf"
    font_file.write_bytes(b"")
    monkeypatch.setattr("captionforge.cli.default_font", lambda role, extra_dirs=None: "ignored")
    monkeypatch.setattr("captionforge.cli.font_family_name", lambda path: "Custom CJK")

    style = style_from_args(base_args(cjk_font_file=font_file))

    assert style.cjk_font == "Custom CJK"


def test_ass_font_dirs_stages_repeated_font_dirs(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "A.ttf").write_bytes(b"a")
    (second_dir / "B.otf").write_bytes(b"b")
    args = base_args(font_dir=[first_dir, second_dir])

    with ass_font_dirs(args) as dirs:
        assert len(dirs) == 1
        staged_names = {path.name for path in dirs[0].iterdir()}
        assert staged_names == {"A.ttf", "B.otf"}


def test_parse_play_res():
    assert parse_play_res("1920x1080") == (1920, 1080)


def test_parse_play_res_rejects_invalid_value():
    with pytest.raises(ValueError):
        parse_play_res("1080p")


def test_batch_command_parses():
    args = build_parser().parse_args(["batch", "videos", "-o", "out", "--dry-run", "--subtitle", "en", "--subtitle", "zh", "--jobs", "2", "--subtitle-outputs", "both"])
    assert args.command == "batch"
    assert args.input_dir.name == "videos"
    assert args.output_dir.name == "out"
    assert args.dry_run is True
    assert args.subtitle == ["en", "zh"]
    assert args.yes is False
    assert args.jobs == 2
    assert args.subtitle_label_position == "suffix"
    assert args.subtitle_outputs == "both"


def test_burn_command_accepts_exact_hevc_and_av1_encoders():
    parser = build_parser()

    hevc_args = parser.parse_args(["burn", "in.mp4", "captions.srt", "-o", "out.mp4", "--encoder", "hevc_nvenc"])
    av1_args = parser.parse_args(["burn", "in.mp4", "captions.srt", "-o", "out.mp4", "--encoder", "libsvtav1"])

    assert hevc_args.encoder == "hevc_nvenc"
    assert av1_args.encoder == "libsvtav1"


def test_burn_command_accepts_preview_format():
    args = build_parser().parse_args(["burn", "in.mp4", "captions.srt", "-o", "out.mp4", "--preview-image", "preview", "--preview-format", "jxl"])

    assert args.preview_image.name == "preview"
    assert args.preview_format == "jxl"


def test_subtitle_match_score_accepts_zh_suffixes_and_prefixes():
    assert subtitle_match_score("movie", "movie.zh", DEFAULT_SUBTITLE_TAGS) == (1, 2)
    assert subtitle_match_score("movie", "movie-zh-cn", DEFAULT_SUBTITLE_TAGS) == (1, 5)
    assert subtitle_match_score("movie", "zh.movie", DEFAULT_SUBTITLE_TAGS) == (2, 2)
    assert subtitle_match_score("movie", "movie.en", DEFAULT_SUBTITLE_TAGS) is None


def test_find_batch_pairs_matches_language_tagged_subtitles(tmp_path):
    video = tmp_path / "movie.mp4"
    subtitle = tmp_path / "movie.zh-cn.srt"
    prefixed_video = tmp_path / "clip.mov"
    prefixed_subtitle = tmp_path / "zh.clip.vtt"
    for path in (video, subtitle, prefixed_video, prefixed_subtitle):
        path.write_text("", encoding="utf-8")

    assert find_batch_pairs(tmp_path, DEFAULT_SUBTITLE_TAGS) == [
        (prefixed_video, prefixed_subtitle),
        (video, subtitle),
    ]


def test_find_batch_matches_auto_accepts_language_only_subtitle_when_one_video(tmp_path):
    video = tmp_path / "movie.mp4"
    subtitle = tmp_path / "en.srt"
    video.write_text("", encoding="utf-8")
    subtitle.write_text("", encoding="utf-8")

    matches = find_batch_matches(tmp_path, ["auto"])

    assert len(matches) == 1
    assert matches[0].video == video
    assert matches[0].subtitles == [subtitle]


def test_find_batch_matches_can_select_multiple_language_subtitles(tmp_path):
    video = tmp_path / "movie.mp4"
    en = tmp_path / "en.srt"
    zh = tmp_path / "zh.srt"
    for path in (video, en, zh):
        path.write_text("", encoding="utf-8")

    matches = find_batch_matches(tmp_path, ["en", "zh"])

    assert len(matches) == 1
    assert matches[0].video == video
    assert matches[0].subtitles == [en, zh]


def test_find_batch_matches_supports_label_prefix_without_separator(tmp_path):
    video = tmp_path / "movie.mp4"
    zh = tmp_path / "中文movie.srt"
    en = tmp_path / "Englishmovie.srt"
    for path in (video, zh, en):
        path.write_text("", encoding="utf-8")

    matches = find_batch_matches(tmp_path, ["中文", "english"])

    assert len(matches) == 1
    assert matches[0].subtitles == [zh, en]


def test_find_batch_matches_auto_raises_when_multiple_subtitles_match(tmp_path):
    video = tmp_path / "movie.mp4"
    en = tmp_path / "movie.en.srt"
    zh = tmp_path / "movie.zh.srt"
    for path in (video, en, zh):
        path.write_text("", encoding="utf-8")

    with pytest.raises(AmbiguousSubtitleError):
        find_batch_matches(tmp_path, ["auto"])


def test_batch_output_path_preserves_relative_parent(tmp_path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    video = input_dir / "nested" / "movie.mp4"

    assert batch_output_path(video, input_dir, output_dir, "-captioned") == output_dir / "nested" / "movie-captioned.mp4"


def test_subtitle_label_for_video_uses_language_key(tmp_path):
    video = tmp_path / "movie.mp4"

    assert subtitle_label_for_video(video, tmp_path / "movie.zh-cn.srt") == "zh-cn"
    assert subtitle_label_for_video(video, tmp_path / "Englishmovie.srt") == "english"
    assert subtitle_label_for_video(video, tmp_path / "movie.srt") == "subtitles"


def test_batch_outputs_can_write_separate_and_combined_files(tmp_path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    video = input_dir / "movie.mp4"
    en = input_dir / "movie.en.srt"
    zh = input_dir / "movie.zh-cn.srt"
    args = base_args(
        output_dir=output_dir,
        output_suffix="-captioned",
        subtitle_outputs="both",
        subtitle_label_position="suffix",
    )

    outputs = batch_outputs_for_match(args, BatchMatch(video, [en, zh]), input_dir)

    assert [output.output for output in outputs] == [
        output_dir / "movie-captioned.en.mp4",
        output_dir / "movie-captioned.zh-cn.mp4",
        output_dir / "movie-captioned.en.zh-cn.mp4",
    ]


def test_batch_outputs_support_prefix_labels(tmp_path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    video = input_dir / "movie.mp4"
    subtitle = input_dir / "movie.zh-cn.srt"
    args = base_args(
        output_dir=output_dir,
        output_suffix="-captioned",
        subtitle_outputs="combined",
        subtitle_label_position="prefix",
    )

    outputs = batch_outputs_for_match(args, BatchMatch(video, [subtitle]), input_dir)

    assert outputs[0].output == output_dir / "zh-cn.movie-captioned.mp4"


def test_batch_outputs_reject_duplicate_output_paths(tmp_path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    video = input_dir / "movie.mp4"
    en = input_dir / "movie.en.srt"
    zh = input_dir / "movie.zh.srt"
    args = base_args(
        output_dir=output_dir,
        output_suffix="-captioned",
        subtitle_outputs="both",
        subtitle_label_position="none",
    )

    with pytest.raises(ValueError, match="filenames collide"):
        batch_outputs_for_matches(args, [BatchMatch(video, [en, zh])], input_dir)


def test_batch_outputs_reject_soft_combined_multi_subtitle_outputs(tmp_path):
    video = tmp_path / "movie.mp4"
    en = tmp_path / "movie.en.srt"
    zh = tmp_path / "movie.zh.srt"
    args = base_args(mode="soft")
    outputs = [BatchMatch(video, [en, zh])]

    with pytest.raises(ValueError, match="Soft subtitle batch mode"):
        validate_batch_outputs(args, batch_outputs_for_matches(base_args(output_dir=tmp_path, output_suffix="-captioned", subtitle_outputs="combined", subtitle_label_position="suffix"), outputs, tmp_path))


def test_run_batch_jobs_processes_matches_and_prints_progress(monkeypatch, capsys, tmp_path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    video = input_dir / "movie.mp4"
    subtitle = input_dir / "movie.srt"
    video.write_text("", encoding="utf-8")
    subtitle.write_text("", encoding="utf-8")
    calls = []
    args = base_args(jobs=1, output_dir=output_dir, output_suffix="-captioned")

    def fake_burn_one(args, video, subtitles, output, style, font_rules=None):
        calls.append((video, subtitles, output))

    monkeypatch.setattr("captionforge.cli.burn_one", fake_burn_one)

    run_batch_jobs(args, [BatchMatch(video, [subtitle])], input_dir, style_from_args(base_args()))

    assert calls == [(video, [subtitle], output_dir / "movie-captioned.subtitles.mp4")]
    assert "Batch progress: 1/1 complete" in capsys.readouterr().out


def test_run_batch_jobs_supports_parallel_jobs(monkeypatch, tmp_path):
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    matches = []
    calls = []
    for index in range(2):
        video = input_dir / f"movie{index}.mp4"
        subtitle = input_dir / f"movie{index}.srt"
        video.write_text("", encoding="utf-8")
        subtitle.write_text("", encoding="utf-8")
        matches.append(BatchMatch(video, [subtitle]))

    args = base_args(jobs=2, output_dir=output_dir, output_suffix="-captioned")

    def fake_burn_one(args, video, subtitles, output, style, font_rules=None):
        calls.append(output)

    monkeypatch.setattr("captionforge.cli.burn_one", fake_burn_one)

    run_batch_jobs(args, matches, input_dir, style_from_args(base_args()))

    assert sorted(path.name for path in calls) == ["movie0-captioned.subtitles.mp4", "movie1-captioned.subtitles.mp4"]


def test_burn_one_passes_multiple_subtitles_to_rounded_renderer(monkeypatch, tmp_path):
    captured = {}
    args = base_args(
        mode="hard",
        render_mode="rounded",
        quality="medium",
        rounded_fps=None,
        reference_height=1080,
        verbose_ffmpeg=False,
        ffmpeg_arg=[],
        encoder="auto",
        codec="h264",
        font_dir=[],
        output_res=None,
        preview_image=None,
        preview_only=False,
        preview_format="auto",
    )
    subtitles = [tmp_path / "movie.en.srt", tmp_path / "movie.zh.srt"]

    def fake_rounded_subtitles(video, subtitle, output, *args):
        captured["subtitle"] = subtitle
        captured["preview_format"] = args[-2]
        captured["font_rules"] = args[-1]

    monkeypatch.setattr("captionforge.cli.rounded_subtitles", fake_rounded_subtitles)

    burn_one(args, tmp_path / "movie.mp4", subtitles, tmp_path / "out.mp4", style_from_args(base_args()))

    assert captured["subtitle"] == subtitles
    assert captured["preview_format"] == "auto"
    assert captured["font_rules"] is None


def test_burn_one_selects_encoder_against_subtitle_ffmpeg(monkeypatch, tmp_path):
    captured = {}
    args = base_args(
        mode="hard",
        render_mode="ass",
        quality="medium",
        reference_height=1080,
        verbose_ffmpeg=False,
        ffmpeg_arg=[],
        encoder="auto",
        codec="hevc",
        font_dir=[],
        keep_ass=None,
        multi_subtitle_layout="stack",
        output_res=None,
    )

    monkeypatch.setattr("captionforge.cli.probe_video_size", lambda video: (1920, 1080))
    monkeypatch.setattr("captionforge.cli.ffmpeg_path", lambda require_subtitles=False: "/opt/ffmpeg-full/bin/ffmpeg")
    def fake_select_encoder(preferred, codec, ffmpeg=None):
        captured["select"] = (preferred, codec, ffmpeg)
        return "libx265"

    monkeypatch.setattr("captionforge.cli.select_encoder", fake_select_encoder)
    monkeypatch.setattr("captionforge.cli.write_multi_ass", lambda subtitles, output, *args: output)
    def fake_burn_subtitles(video, ass, output, extra, quality, font_dirs, verbose, encoder, ffmpeg=None, output_res=None, fallback_encoder=None):
        captured["encoder"] = encoder
        captured["burn_ffmpeg"] = ffmpeg
        captured["output_res"] = output_res
        captured["fallback_encoder"] = fallback_encoder

    monkeypatch.setattr("captionforge.cli.burn_subtitles", fake_burn_subtitles)

    burn_one(args, tmp_path / "movie.mp4", tmp_path / "movie.srt", tmp_path / "out.mp4", style_from_args(base_args()))

    assert captured["select"] == ("auto", "hevc", "/opt/ffmpeg-full/bin/ffmpeg")
    assert captured["burn_ffmpeg"] == "/opt/ffmpeg-full/bin/ffmpeg"
    assert captured["output_res"] is None
    assert captured["fallback_encoder"] is None


def test_burn_one_passes_output_resolution_to_ass_renderer(monkeypatch, tmp_path):
    captured = {}
    args = base_args(
        mode="hard",
        render_mode="ass",
        quality="medium",
        reference_height=1080,
        verbose_ffmpeg=False,
        ffmpeg_arg=[],
        encoder="cpu",
        codec="h264",
        font_dir=[],
        keep_ass=None,
        multi_subtitle_layout="stack",
        output_res="3840x2160",
    )

    monkeypatch.setattr("captionforge.cli.ffmpeg_path", lambda require_subtitles=False: "/bin/echo")
    monkeypatch.setattr("captionforge.cli.select_encoder", lambda preferred, codec, ffmpeg=None: "libx264")

    def fake_write_multi_ass(subtitles, output, style, play_res, *args):
        captured["play_res"] = play_res
        return output

    def fake_burn_subtitles(video, ass, output, extra, quality, font_dirs, verbose, encoder, ffmpeg=None, output_res=None, fallback_encoder=None):
        captured["output_res"] = output_res

    monkeypatch.setattr("captionforge.cli.write_multi_ass", fake_write_multi_ass)
    monkeypatch.setattr("captionforge.cli.burn_subtitles", fake_burn_subtitles)

    burn_one(args, tmp_path / "movie.mp4", tmp_path / "movie.srt", tmp_path / "out.mp4", style_from_args(base_args()))

    assert captured["play_res"] == (3840, 2160)
    assert captured["output_res"] == (3840, 2160)


def test_resolve_codec_auto_follows_probe(monkeypatch, tmp_path):
    monkeypatch.setattr("captionforge.cli.probe_video_codec", lambda video: "hevc")

    assert resolve_codec(tmp_path / "movie.mp4", "auto") == "hevc"
    assert resolve_codec(tmp_path / "movie.mp4", "h264") == "h264"


def test_burn_one_sets_cpu_fallback_for_auto_videotoolbox(monkeypatch, tmp_path):
    captured = {}
    args = base_args(
        mode="hard",
        render_mode="ass",
        quality="medium",
        reference_height=1080,
        verbose_ffmpeg=False,
        ffmpeg_arg=[],
        encoder="auto",
        codec="hevc",
        font_dir=[],
        keep_ass=None,
        multi_subtitle_layout="stack",
        output_res=None,
    )

    monkeypatch.setattr("captionforge.cli.probe_video_size", lambda video: (1920, 1080))
    monkeypatch.setattr("captionforge.cli.ffmpeg_path", lambda require_subtitles=False: "/bin/echo")
    monkeypatch.setattr(
        "captionforge.cli.select_encoder",
        lambda preferred, codec, ffmpeg=None: "libx265" if preferred == "cpu" else "hevc_videotoolbox",
    )
    monkeypatch.setattr("captionforge.cli.write_multi_ass", lambda subtitles, output, *args: output)

    def fake_burn_subtitles(video, ass, output, extra, quality, font_dirs, verbose, encoder, ffmpeg=None, output_res=None, fallback_encoder=None):
        captured["encoder"] = encoder
        captured["fallback_encoder"] = fallback_encoder

    monkeypatch.setattr("captionforge.cli.burn_subtitles", fake_burn_subtitles)

    burn_one(args, tmp_path / "movie.mp4", tmp_path / "movie.srt", tmp_path / "out.mp4", style_from_args(base_args()))

    assert captured["encoder"] == "hevc_videotoolbox"
    assert captured["fallback_encoder"] == "libx265"
