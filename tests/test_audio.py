import json
import random
import shutil
import subprocess

import pytest

from reels_autopublish import audio


def make_tracks(folder, n):
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (folder / f"track_{i}.mp3").write_bytes(b"")
    (folder / "notes.txt").write_text("ignored")
    return audio.find_tracks(folder)


def test_find_tracks_ignores_other_files(tmp_path):
    assert [t.name for t in make_tracks(tmp_path, 3)] == ["track_0.mp3", "track_1.mp3", "track_2.mp3"]


def test_pick_avoids_recent(tmp_path):
    tracks = make_tracks(tmp_path, 4)
    for seed in range(50):
        pick = audio.pick_track(tracks, ["track_0.mp3", "track_1.mp3"], 2, random.Random(seed))
        assert pick.name in {"track_2.mp3", "track_3.mp3"}


def test_pick_relaxes_with_few_tracks(tmp_path):
    tracks = make_tracks(tmp_path, 2)
    for seed in range(20):
        pick = audio.pick_track(tracks, ["track_0.mp3", "track_1.mp3"], 2, random.Random(seed))
        assert pick.name == "track_0.mp3"  # only the very last one stays blocked


def test_pick_single_track(tmp_path):
    tracks = make_tracks(tmp_path, 1)
    assert audio.pick_track(tracks, ["track_0.mp3"], 2).name == "track_0.mp3"


def test_remember_keeps_window(tmp_path):
    state = tmp_path / "state" / "audio.json"
    for name in ["a.mp3", "b.mp3", "c.mp3"]:
        audio.remember(state, tmp_path / name, keep=2)
    assert json.loads(state.read_text())["last_used"] == ["b.mp3", "c.mp3"]


def test_ffmpeg_command_fades_at_the_end(tmp_path):
    cmd = audio.ffmpeg_command(tmp_path / "v.mp4", tmp_path / "t.mp3", tmp_path / "o.mp4", 7.0, 0.3, 0.4)
    assert "afade=t=out:st=6.600:d=0.4" in cmd[cmd.index("-filter_complex") + 1]
    assert cmd[cmd.index("-c:v") + 1] == "copy"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_mux_end_to_end(cfg):
    cfg.tracks_dir.mkdir(parents=True)
    silent = cfg.root / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x568:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    str(cfg.tracks_dir / "tone.mp3")], check=True, capture_output=True)
    out = cfg.root / "out.mp4"

    track = audio.mux(cfg, silent, out)

    assert track.name == "tone.mp3"
    assert abs(audio.probe_duration(out) - 2.0) < 0.2
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                              "-of", "csv=p=0", str(out)], check=True, capture_output=True, text=True).stdout.split()
    assert sorted(streams) == ["audio", "video"]
    assert "tone.mp3" in cfg.audio_log.read_text()
