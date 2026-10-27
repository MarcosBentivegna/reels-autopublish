import datetime

from reels_autopublish import cli


def test_cleanup_dry_run(tmp_path, capsys):
    (tmp_path / "output" / "20200101" / "videos").mkdir(parents=True)
    (tmp_path / "reels.toml").write_text("")
    code = cli.main(["--config", str(tmp_path / "reels.toml"), "cleanup", "--dry-run"])
    assert code == 0
    assert "1 day folder(s)" in capsys.readouterr().out
    assert (tmp_path / "output" / "20200101").exists()
    assert datetime.date.today().year >= 2020


def test_preflight_all_skipped(tmp_path, capsys):
    code = cli.main(["--config", str(tmp_path / "reels.toml"), "preflight", "--skip",
                     "binaries", "disk", "tracks", "state", "drive", "buffer"])
    assert code == 0
    assert "PREFLIGHT OK" in capsys.readouterr().out
