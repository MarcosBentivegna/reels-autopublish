import json

import pytest

from reels_autopublish.buffer import BufferClient, BufferError


class FakeTransport:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or []

    def __call__(self, query, variables, token):
        self.calls.append((query, variables, token))
        if self.responses:
            return self.responses.pop(0)
        post_id = f"p{len(self.calls)}"
        return {"data": {"createPost": {"__typename": "PostActionSuccess", "post": {"id": post_id}}}}


@pytest.fixture
def client(cfg):
    cfg.buffer_channels.parent.mkdir(parents=True)
    cfg.buffer_channels.write_text(json.dumps({"instagram": "ig", "tiktok": "tk", "youtube": "yt"}))
    transport = FakeTransport()
    return BufferClient(cfg, transport=transport, token="t0k"), transport


def inputs(transport):
    return [variables["input"] for _, variables, _ in transport.calls]


def test_publish_reel_three_networks_and_log(client, cfg):
    c, transport = client
    result = c.publish_reel("caption", "https://x/v.mp4", "YT title", "TK title",
                            due_at="2026-11-02T18:00:00Z", thumbnail_offset_ms=4500, video_name="v.mp4")

    ig, tk, yt = inputs(transport)
    assert [i["channelId"] for i in (ig, tk, yt)] == ["ig", "tk", "yt"]
    assert all(i["mode"] == "customScheduled" for i in (ig, tk, yt))
    # cover offset only where the networks accept it
    assert ig["assets"][0]["video"]["metadata"] == {"thumbnailOffset": 4500}
    assert "metadata" not in yt["assets"][0]["video"]
    assert yt["metadata"]["youtube"]["categoryId"] == "22"
    assert result["instagram"]["id"] == "p1"
    row = cfg.publish_log.read_text().splitlines()[1].split(",")
    assert row[1:] == ["v.mp4", "2026-11-02T18:00:00Z", "p1", "p2", "p3"]


def test_publish_now_without_due_at(client):
    c, transport = client
    c.publish_reel("c", "u", "t", "t", networks=("tiktok",))
    (only,) = inputs(transport)
    assert only["mode"] == "shareNow" and "dueAt" not in only


def test_drafts_are_not_logged(client, cfg):
    c, transport = client
    c.publish_reel("c", "u", "t", "t", save_to_draft=True, video_name="v.mp4")
    assert all(i["saveToDraft"] for i in inputs(transport))
    assert not cfg.publish_log.exists()


def test_carousel_is_a_multi_image_post(client):
    c, transport = client
    c.publish_carousel("c", ["https://x/1.png", "https://x/2.png"], "t")
    ig, tk = inputs(transport)
    assert ig["metadata"]["instagram"]["type"] == "post"
    assert len(ig["assets"]) == 2
    assert tk["channelId"] == "tk" and tk["assets"] == ig["assets"]


def test_edit_always_sends_mode(client):
    c, transport = client
    transport.responses = [{"data": {"editPost": {"__typename": "PostActionSuccess", "post": {"id": "p"}}}}]
    c.edit_post("p", "2026-11-03T10:00:00Z", "c", [{"video": {"url": "u"}}])
    (edit,) = inputs(transport)
    assert edit["mode"] == "customScheduled" and edit["text"] == "c" and edit["assets"]


def test_mutation_error_raises(client):
    c, transport = client
    transport.responses = [{"data": {"createPost": {"__typename": "InvalidInputError", "message": "nope"}}}]
    with pytest.raises(BufferError, match="nope"):
        c.create_post("ig", "c", [])


def test_graphql_errors_raise(client):
    c, transport = client
    transport.responses = [{"errors": [{"message": "unauthorized"}]}]
    with pytest.raises(BufferError, match="unauthorized"):
        c.organization_id()


def test_token_read_from_secrets(cfg):
    cfg.secrets_dir.mkdir(parents=True)
    cfg.buffer_token.write_text("  abc\n")
    transport = FakeTransport([{"data": {"account": {"organizations": [{"id": "o1", "name": "x"}]}}}])
    assert BufferClient(cfg, transport=transport).organization_id() == "o1"
    assert transport.calls[0][2] == "abc"
