from pathlib import Path

from captionforge.ffmpeg import burn_subtitles, encode_args, escape_filter_path, ffmpeg_path, probe_fps, probe_video_codec, select_encoder, soft_subtitles


def test_escape_filter_path_escapes_filtergraph_special_chars():
    escaped = escape_filter_path(Path("/tmp/a,b[c];d.ass"))
    assert r"\," in escaped
    assert r"\[" in escaped
    assert r"\]" in escaped
    assert r"\;" in escaped


def test_encode_args_uses_webm_codec_for_webm():
    assert encode_args(Path("out.webm"), "medium") == ["-c:v", "libvpx-vp9", "-crf", "28", "-b:v", "0"]


def test_encode_args_supports_hevc_software_encoder():
    assert encode_args(Path("out.mp4"), "high", "libx265") == ["-c:v", "libx265", "-crf", "23", "-preset", "medium"]


def test_encode_args_supports_av1_software_encoder():
    assert encode_args(Path("out.mp4"), "low", "libsvtav1") == ["-c:v", "libsvtav1", "-crf", "32", "-preset", "8"]


def test_encode_args_supports_exact_gpu_encoder():
    assert encode_args(Path("out.mp4"), "medium", "hevc_nvenc") == [
        "-c:v",
        "hevc_nvenc",
        "-rc",
        "vbr",
        "-cq",
        "28",
        "-preset",
        "medium",
    ]


def test_encode_args_supports_videotoolbox_encoder():
    assert encode_args(Path("out.mp4"), "medium", "h264_videotoolbox") == ["-c:v", "h264_videotoolbox", "-q:v", "28"]


def test_select_encoder_combines_codec_and_platform(monkeypatch):
    monkeypatch.setattr("captionforge.ffmpeg.available_encoders", lambda ffmpeg=None: {"hevc_nvenc", "av1_qsv"})

    assert select_encoder("nvenc", "hevc") == "hevc_nvenc"
    assert select_encoder("qsv", "av1") == "av1_qsv"


def test_select_encoder_accepts_exact_encoder_name():
    assert select_encoder("libsvtav1", "h264") == "libsvtav1"
    assert select_encoder("hevc_nvenc", "h264") == "hevc_nvenc"


def test_select_encoder_uses_requested_ffmpeg_for_auto(monkeypatch):
    captured = {}

    def fake_available_encoders(ffmpeg=None):
        captured["ffmpeg"] = ffmpeg
        return {"hevc_qsv", "libx265"}

    monkeypatch.setattr("captionforge.ffmpeg.available_encoders", fake_available_encoders)

    assert select_encoder("auto", "hevc", "/opt/ffmpeg-full/bin/ffmpeg") == "hevc_qsv"
    assert captured["ffmpeg"] == "/opt/ffmpeg-full/bin/ffmpeg"


def test_select_encoder_prefers_videotoolbox_on_macos(monkeypatch):
    monkeypatch.setattr("captionforge.ffmpeg.platform.system", lambda: "Darwin")
    monkeypatch.setattr("captionforge.ffmpeg.available_encoders", lambda ffmpeg=None: {"h264_videotoolbox", "h264_nvenc", "libx264"})

    assert select_encoder("auto", "h264", "/opt/homebrew/bin/ffmpeg") == "h264_videotoolbox"


def test_select_encoder_platform_falls_back_when_unavailable(monkeypatch):
    monkeypatch.setattr("captionforge.ffmpeg.available_encoders", lambda ffmpeg=None: {"libsvtav1"})

    assert select_encoder("videotoolbox", "av1", "/opt/homebrew/bin/ffmpeg") == "libsvtav1"


def test_ffmpeg_env_override(monkeypatch):
    monkeypatch.setenv("CAPTIONFORGE_FFMPEG", "/bin/echo")
    assert ffmpeg_path() == "/bin/echo"


def test_probe_fps_falls_back_for_zero_rates(monkeypatch, tmp_path):
    class Result:
        stdout = "0/0\n0/0\n"

    monkeypatch.setattr("captionforge.ffmpeg.ffprobe_path", lambda: "/bin/echo")
    monkeypatch.setattr("captionforge.ffmpeg.subprocess.run", lambda *args, **kwargs: Result())

    assert probe_fps(tmp_path / "in.mp4") == 24.0


def test_probe_video_codec_maps_hevc(monkeypatch, tmp_path):
    class Result:
        stdout = "hevc\n"

    monkeypatch.setattr("captionforge.ffmpeg.ffprobe_path", lambda: "/bin/echo")
    monkeypatch.setattr("captionforge.ffmpeg.subprocess.run", lambda *args, **kwargs: Result())

    assert probe_video_codec(tmp_path / "in.mp4") == "hevc"


def test_burn_subtitles_uses_quiet_ffmpeg(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr("captionforge.ffmpeg.require_subtitle_filter", lambda: "/bin/echo")
    monkeypatch.setattr("captionforge.ffmpeg.available_filters", lambda ffmpeg=None: {"ass"})
    monkeypatch.setattr("captionforge.ffmpeg.subprocess.run", lambda cmd, check: captured.setdefault("cmd", cmd))

    burn_subtitles(tmp_path / "in.mp4", tmp_path / "in.ass", tmp_path / "out.mp4")

    assert "-loglevel" in captured["cmd"]
    assert "error" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-map") + 1 : captured["cmd"].index("-map") + 2] == ["0:v:0"]
    assert "0:a?" in captured["cmd"]


def test_burn_subtitles_scales_before_ass_filter(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr("captionforge.ffmpeg.require_subtitle_filter", lambda: "/bin/echo")
    monkeypatch.setattr("captionforge.ffmpeg.available_filters", lambda ffmpeg=None: {"ass"})
    monkeypatch.setattr("captionforge.ffmpeg.subprocess.run", lambda cmd, check: captured.setdefault("cmd", cmd))

    burn_subtitles(tmp_path / "in.mp4", tmp_path / "in.ass", tmp_path / "out.mp4", output_res=(3840, 2160))

    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert vf.startswith("scale=3840:2160:flags=lanczos,ass=")


def test_burn_subtitles_retries_with_fallback_encoder(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr("captionforge.ffmpeg.require_subtitle_filter", lambda: "/bin/echo")
    monkeypatch.setattr("captionforge.ffmpeg.available_filters", lambda ffmpeg=None: {"ass"})

    def fake_run(cmd, check):
        calls.append(cmd)
        if len(calls) == 1:
            raise __import__("subprocess").CalledProcessError(1, cmd)

    monkeypatch.setattr("captionforge.ffmpeg.subprocess.run", fake_run)

    burn_subtitles(
        tmp_path / "in.mp4",
        tmp_path / "in.ass",
        tmp_path / "out.mp4",
        encoder="hevc_videotoolbox",
        fallback_encoder="libx265",
    )

    assert "hevc_videotoolbox" in calls[0]
    assert "libx265" in calls[1]


def test_soft_subtitles_maps_video_audio_and_new_subtitle(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr("captionforge.ffmpeg.require_ffmpeg", lambda: "/bin/echo")
    monkeypatch.setattr("captionforge.ffmpeg.subprocess.run", lambda cmd, check: captured.setdefault("cmd", cmd))

    soft_subtitles(tmp_path / "in.mp4", tmp_path / "captions.srt", tmp_path / "out.mp4")

    assert "-map" in captured["cmd"]
    assert "0:v:0" in captured["cmd"]
    assert "0:a?" in captured["cmd"]
    assert "1:0" in captured["cmd"]
