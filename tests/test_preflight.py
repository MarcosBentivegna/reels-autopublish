import json

from reels_autopublish import preflight
from reels_autopublish.preflight import FAIL, OK, WARN


class FakeBuffer:
    def __init__(self, live, saved):
        self.live, self.saved = live, saved

    def list_channels(self):
        return [{"service": s, "id": i} for s, i in self.live.items()]

    def load_channels(self):
        return self.saved


def secrets(cfg):
    cfg.secrets_dir.mkdir(parents=True, exist_ok=True)
    cfg.buffer_token.write_text("t")
    cfg.buffer_channels.write_text("{}")


def test_buffer_ids_match(cfg):
    secrets(cfg)
    (r,) = preflight.check_buffer(cfg, FakeBuffer({"instagram": "1"}, {"instagram": "1"}))
    assert r.level == OK


def test_buffer_ids_changed(cfg):
    secrets(cfg)
    (r,) = preflight.check_buffer(cfg, FakeBuffer({"instagram": "2"}, {"instagram": "1"}))
    assert r.level == FAIL and "instagram" in r.detail


def test_buffer_missing_token(cfg):
    (r,) = preflight.check_buffer(cfg)
    assert r.level == FAIL


def test_drive_missing_files(cfg):
    (r,) = preflight.check_drive(cfg)
    assert r.level == FAIL and "credentials" in r.detail


def test_state_broken_json(cfg):
    cfg.state_dir.mkdir()
    (cfg.state_dir / "ok.json").write_text(json.dumps({"a": 1}))
    (cfg.state_dir / "bad.json").write_text("{nope")
    (r,) = preflight.check_state(cfg)
    assert r.level == FAIL and "bad.json" in r.detail


def test_missing_binary(cfg):
    cfg.required_binaries = ("definitely-not-a-real-binary",)
    (r,) = preflight.check_binaries(cfg)
    assert r.level == FAIL


def test_report_exit_codes():
    assert preflight.report([preflight.Result(OK, "a"), preflight.Result(WARN, "b")])[1] == 0
    text, code = preflight.report([preflight.Result(FAIL, "c", "broken")])
    assert code == 1 and "broken" in text


def test_skip(cfg):
    results = preflight.run(cfg, skip={"binaries", "disk", "tracks", "state", "drive", "buffer"})
    assert all(r.level == WARN and r.detail == "skipped" for r in results)
