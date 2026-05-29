from __future__ import annotations

from track_fraude.evidence.video_source import _web_video_encode_args
from track_fraude_core.db.evidence_ffmpeg import evidence_encode_settings


def test_web_video_encode_args_defaults_no_scale():
    args = _web_video_encode_args(scale_width=None, preset="fast", crf=28)
    assert "-vf" not in args
    assert args[args.index("-crf") + 1] == "28"
    assert args[args.index("-preset") + 1] == "fast"
    assert "+faststart" in args


def test_web_video_encode_args_with_scale():
    settings = evidence_encode_settings(scale_width=1280, preset="faster", crf=28)
    args = _web_video_encode_args(
        scale_width=settings.scale_width,
        preset=settings.preset,
        crf=settings.crf,
    )
    assert "scale=1280:-2" in args
    assert args[args.index("-crf") + 1] == "28"


def test_normalize_blank_scale():
    settings = evidence_encode_settings(scale_width="", preset="fast", crf=28)
    assert settings.scale_width is None
