import pytest

from reels_autopublish.config import load_config


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "reels.toml").write_text('[drive]\npublic_suffixes = [".mp4"]\n', encoding="utf-8")
    return load_config(tmp_path / "reels.toml")
