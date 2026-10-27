from reels_autopublish.config import load_config


def test_defaults_without_file(tmp_path):
    cfg = load_config(tmp_path / "reels.toml")
    assert cfg.output_dir == tmp_path / "output"
    assert cfg.drive_token == tmp_path / "secrets" / "token.json"
    assert cfg.audio_avoid_last == 2


def test_paths_resolve_against_config_folder(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "reels.toml").write_text('[paths]\nsecrets_dir = "../vault"\n[audio]\navoid_last = 3\n')
    monkeypatch.chdir(tmp_path)
    cfg = load_config(project / "reels.toml")
    assert cfg.secrets_dir == (tmp_path / "vault").resolve()
    assert cfg.audio_avoid_last == 3


def test_env_var(tmp_path, monkeypatch):
    (tmp_path / "custom.toml").write_text('[drive]\nvideo_folder = "shorts"\n')
    monkeypatch.setenv("REELS_CONFIG", str(tmp_path / "custom.toml"))
    assert load_config().drive_video_folder == "shorts"
