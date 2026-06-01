import subprocess
from types import SimpleNamespace

from PIL import Image, ImageFont

from captionforge.rounded import (
    _build_segments,
    aligned_box_position,
    preview_output_path,
    preview_codec_args,
    plain_text,
    render_frame,
    resolve_preview_format,
    rgba,
    save_composited_preview,
    rounded_subtitles,
)
from captionforge.styles import CaptionStyle


def test_plain_text_removes_ass_tags_and_newlines():
    assert plain_text(r"{\i1}Hello\N世界") == "Hello\n世界"


def test_rgba_converts_ass_alpha_to_pillow_alpha():
    assert rgba("#000000", 255) == (0, 0, 0, 0)
    assert rgba("#000000", 0) == (0, 0, 0, 255)


def test_render_frame_draws_rounded_box_pixels():
    font = ImageFont.load_default()
    frame = render_frame(
        (320, 180),
        ["Hello"],
        CaptionStyle(background_alpha=0, primary_alpha=0, font_size=20),
        {"cjk": font, "latin": font},
    )
    assert frame.getbbox() is not None


def test_aligned_box_position_supports_middle_height():
    style = CaptionStyle(alignment=5, margin_v=20, margin_l=10, margin_r=15)

    assert aligned_box_position((320, 180), (100, 40), style) == (110, 70)


def test_aligned_box_position_supports_top_right():
    style = CaptionStyle(alignment=9, margin_v=20, margin_l=10, margin_r=15)

    assert aligned_box_position((320, 180), (100, 40), style) == (205, 20)


def test_aligned_box_position_clamps_oversized_boxes_to_frame():
    style = CaptionStyle(alignment=2, margin_v=20, margin_l=10, margin_r=15)

    assert aligned_box_position((320, 180), (400, 220), style) == (0, 0)


def test_build_segments_preserves_subtitle_track_order():
    segments = _build_segments(
        [
            (0.0, 1.0, 1, "中文"),
            (0.0, 1.0, 0, "English"),
        ],
        1.0,
    )

    assert segments == [(0.0, 1.0, ["English", "中文"])]


def test_save_composited_preview_uses_video_frame(monkeypatch, tmp_path):
    captured = {}

    def fake_extract(video, timestamp, size, ffmpeg=None):
        captured["timestamp"] = timestamp
        captured["size"] = size
        return Image.new("RGBA", size, (255, 0, 0, 255))

    monkeypatch.setattr("captionforge.rounded.extract_video_frame", fake_extract)

    overlay = Image.new("RGBA", (8, 8), (0, 0, 255, 128))
    output = tmp_path / "preview.jpg"
    save_composited_preview(tmp_path / "in.mp4", 1.25, overlay, output)

    assert captured == {"timestamp": 1.25, "size": (8, 8)}
    assert output.exists()
    pixel = Image.open(output).convert("RGB").getpixel((4, 4))
    assert pixel[0] > 100
    assert pixel[2] > 100


def test_hdr_preview_falls_back_to_png_when_encoder_fails(monkeypatch, tmp_path, capsys):
    captured = {}

    def fake_extract(video, timestamp, size, ffmpeg=None):
        captured["extract"] = (timestamp, size)
        return Image.new("RGBA", size, (0, 255, 0, 255))

    monkeypatch.setattr("captionforge.rounded.available_encoders", lambda ffmpeg=None: set())
    monkeypatch.setattr("captionforge.rounded.extract_video_frame", fake_extract)

    output = tmp_path / "preview.avif"
    written = save_composited_preview(
        tmp_path / "in.mp4",
        1.0,
        Image.new("RGBA", (8, 8), (255, 0, 0, 128)),
        output,
        "/bin/ffmpeg",
        "avif",
        {"color_transfer": "smpte2084"},
    )

    assert written == tmp_path / "preview.png"
    assert written.exists()
    assert not output.exists()
    assert captured["extract"] == (1.0, (8, 8))
    assert "AVIF preview failed" in capsys.readouterr().out


def test_preview_format_auto_uses_png_for_sdr_and_avif_for_hdr(tmp_path):
    assert resolve_preview_format("auto", {}) == "png"
    assert resolve_preview_format("auto", {"color_transfer": "bt709"}) == "png"
    assert resolve_preview_format("auto", {"color_transfer": "smpte2084"}) == "avif"
    assert resolve_preview_format("jxl", {"color_transfer": "smpte2084"}) == "jxl"
    assert resolve_preview_format("jpeg", {}) == "jpg"
    assert preview_output_path(tmp_path / "preview.jpg", "avif") == tmp_path / "preview.avif"


def test_hdr_preview_uses_ffmpeg_encoder_and_color_metadata(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, check):
        captured["cmd"] = cmd

    monkeypatch.setattr("captionforge.rounded.subprocess.run", fake_run)
    monkeypatch.setattr("captionforge.rounded.available_encoders", lambda ffmpeg=None: {"libjxl"})

    overlay = Image.new("RGBA", (16, 8), (255, 255, 255, 128))
    save_composited_preview(
        tmp_path / "in.mp4",
        2.5,
        overlay,
        tmp_path / "preview.jxl",
        "/bin/ffmpeg",
        "jxl",
        {"color_primaries": "bt2020", "color_transfer": "smpte2084", "color_space": "bt2020nc"},
    )

    cmd = captured["cmd"]
    assert "-c:v" in cmd
    assert "libjxl" in cmd
    assert "format=pix_fmts=rgb48le[v]" in cmd[cmd.index("-filter_complex") + 1]
    assert ["-color_primaries", "bt2020"] == cmd[cmd.index("-color_primaries") : cmd.index("-color_primaries") + 2]
    assert ["-color_trc", "smpte2084"] == cmd[cmd.index("-color_trc") : cmd.index("-color_trc") + 2]


def test_avif_preview_uses_available_av1_encoder(monkeypatch):
    monkeypatch.setattr("captionforge.rounded.available_encoders", lambda ffmpeg=None: {"libsvtav1"})

    assert preview_codec_args("avif", "/bin/ffmpeg") == ["-c:v", "libsvtav1", "-crf", "18"]


def test_rounded_subtitles_builds_vfr_overlay_maps_audio_and_drains_stderr(monkeypatch, tmp_path):
    run_commands = []
    popen_calls = []
    overlay_frame = {}

    class FakeStdout:
        def __init__(self):
            self.lines = iter(["out_time_ms=1000000\n", ""])

        def readline(self):
            return next(self.lines)

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            popen_calls.append((cmd, kwargs))
            self.stdout = FakeStdout()
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self):
            return self.returncode

    fake_subs = SimpleNamespace(events=[SimpleNamespace(start=0, end=1000, text="Hello")])

    monkeypatch.setattr("captionforge.rounded.probe_video_size", lambda video: (320, 180))
    monkeypatch.setattr("captionforge.rounded.probe_duration", lambda video: 1.0)
    monkeypatch.setattr("captionforge.rounded.probe_fps", lambda video: 23.976)
    monkeypatch.setattr("captionforge.rounded.probe_pix_fmt", lambda video: "yuv420p")
    monkeypatch.setattr("captionforge.rounded.probe_color_info", lambda video: {})
    monkeypatch.setattr("captionforge.rounded.ffmpeg_path", lambda: "/bin/echo")
    monkeypatch.setattr("captionforge.rounded.select_encoder", lambda encoder, codec, ffmpeg=None: "libx264")
    monkeypatch.setattr("captionforge.rounded.load_subtitles", lambda subtitle: fake_subs)
    monkeypatch.setattr("captionforge.rounded.load_font", lambda font_name, size, font_file=None: ImageFont.load_default())
    def fake_run(cmd, check):
        run_commands.append(cmd)
        if "-f" in cmd and "concat" in cmd:
            concat_path = cmd[cmd.index("-i") + 1]
            first_line = next(line for line in open(concat_path, encoding="utf-8") if line.startswith("file "))
            frame_path = first_line.split("'", 2)[1]
            frame = Image.open(frame_path)
            overlay_frame["mode"] = frame.mode
            overlay_frame["corner"] = frame.convert("RGBA").getpixel((0, 0))

    monkeypatch.setattr("captionforge.rounded.subprocess.run", fake_run)
    monkeypatch.setattr("captionforge.rounded.subprocess.Popen", FakePopen)

    rounded_subtitles(tmp_path / "in.mp4", tmp_path / "captions.srt", tmp_path / "out.mp4", CaptionStyle(), "medium")

    overlay_cmd = run_commands[0]
    burn_cmd, popen_kwargs = popen_calls[0]

    assert "-vsync" in overlay_cmd
    assert "vfr" in overlay_cmd
    assert "-r" not in overlay_cmd
    assert "[v]" in burn_cmd
    assert "0:a?" in burn_cmd
    assert popen_kwargs["stderr"] == subprocess.STDOUT
    assert overlay_frame["mode"] == "RGBA"
    assert overlay_frame["corner"][3] == 0
