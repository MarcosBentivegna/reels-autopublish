"""Client for Buffer's GraphQL API (api.buffer.com/graphql).

Field and enum names were checked against the live schema with introspection,
and every behaviour noted below was seen on real calls, not taken from docs.
The notes matter: several of them are places where the API accepts a request
and then does something other than what the schema suggests.

Why Buffer and not Metricool for daily posting: on the plan tested, Metricool
capped publications at 20 per month, far below one reel a day on three
networks. Metricool stays useful for read-only analytics.
"""
from __future__ import annotations

import csv
import datetime
import json
import urllib.request
from collections.abc import Callable

from .config import Config

GRAPHQL_URL = "https://api.buffer.com/graphql"

Transport = Callable[[str, dict, str], dict]


class BufferError(RuntimeError):
    pass


def _http_transport(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


class BufferClient:
    def __init__(self, cfg: Config, transport: Transport = _http_transport, token: str | None = None):
        self.cfg = cfg
        self._transport = transport
        self._token = token

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = self.cfg.buffer_token.read_text(encoding="utf-8").strip()
        return self._token

    def query(self, query: str, variables: dict | None = None) -> dict:
        result = self._transport(query, variables or {}, self.token)
        if "errors" in result:
            raise BufferError(f"Buffer API error: {result['errors']}")
        return result["data"]

    # -- account -----------------------------------------------------------

    def organization_id(self) -> str:
        data = self.query("query { account { organizations { id name } } }")
        return data["account"]["organizations"][0]["id"]

    def list_channels(self, organization_id: str | None = None) -> list[dict]:
        data = self.query(
            "query($orgId: OrganizationId!) { "
            "channels(input: {organizationId: $orgId}) { id service displayName } }",
            {"orgId": organization_id or self.organization_id()},
        )
        return data["channels"]

    def save_channels(self) -> dict:
        """Writes {service: channel_id} to channels.json. Channel ids are
        stable per connected account, so this runs once, not before every
        post. Preflight re-checks them against the live account."""
        channels = {c["service"]: c["id"] for c in self.list_channels()}
        self.cfg.buffer_channels.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.buffer_channels.write_text(json.dumps(channels, indent=2) + "\n", encoding="utf-8")
        return channels

    def load_channels(self) -> dict:
        return json.loads(self.cfg.buffer_channels.read_text(encoding="utf-8"))

    # -- posts -------------------------------------------------------------

    def create_post(
        self,
        channel_id: str,
        text: str,
        assets: list[dict],
        metadata: dict | None = None,
        due_at: str | None = None,
        save_to_draft: bool = False,
    ) -> dict:
        """assets: [{"image": {"url": ...}}] or [{"video": {"url": ...}}].
        due_at: ISO 8601 UTC; without it the post goes out now (shareNow).

        save_to_draft=True lands the post as a draft that is never sent,
        whatever mode or due_at say. Use it to try any new post shape before
        trusting it with real publishing, then remove it with delete_post.
        """
        input_obj: dict = {
            "channelId": channel_id,
            "text": text,
            "assets": assets,
            "mode": "customScheduled" if due_at else "shareNow",
            "schedulingType": "automatic",
            "needsApproval": False,
        }
        if due_at:
            input_obj["dueAt"] = due_at
        if metadata:
            input_obj["metadata"] = metadata
        if save_to_draft:
            input_obj["saveToDraft"] = True
        data = self.query(
            "mutation($input: CreatePostInput!) { createPost(input: $input) { __typename "
            "... on PostActionSuccess { post { id text dueAt } } "
            "... on MutationError { message } } }",
            {"input": input_obj},
        )
        return _unwrap(data["createPost"], "createPost")

    def edit_post(
        self, post_id: str, due_at: str, text: str, assets: list[dict], metadata: dict | None = None
    ) -> dict:
        """Reschedules an existing post.

        Two traps, both seen on live calls:
        1. Although EditPostInput marks text/assets/metadata as optional,
           Buffer validates the edit as a whole new post. A dueAt-only edit of
           an Instagram post fails with "Instagram posts require at least one
           image or video". Send the same text/assets/metadata as the create.
        2. Without an explicit `mode`, the call returns PostActionSuccess and
           bumps updatedAt, but dueAt does not change. `mode` is always sent.

        Never try this against a post that is really queued: a test edit with
        a placeholder caption that is not reverted goes live as is. Create a
        draft with save_to_draft=True, edit that, then delete it.
        """
        input_obj = {"id": post_id, "dueAt": due_at, "mode": "customScheduled", "text": text, "assets": assets}
        if metadata:
            input_obj["metadata"] = metadata
        data = self.query(
            "mutation($input: EditPostInput!) { editPost(input: $input) { __typename "
            "... on PostActionSuccess { post { id text dueAt } } "
            "... on MutationError { message } } }",
            {"input": input_obj},
        )
        return _unwrap(data["editPost"], "editPost")

    def delete_post(self, post_id: str) -> None:
        data = self.query(
            "mutation($input: DeletePostInput!) { deletePost(input: $input) { __typename } }",
            {"input": {"id": post_id}},
        )
        if data["deletePost"]["__typename"] != "DeletePostSuccess":
            raise BufferError(f"deletePost failed: {data['deletePost']}")

    # -- high level ----------------------------------------------------------

    def publish_reel(
        self,
        text: str,
        video_url: str,
        youtube_title: str,
        tiktok_title: str,
        due_at: str | None = None,
        thumbnail_offset_ms: int | None = None,
        save_to_draft: bool = False,
        video_name: str | None = None,
        networks: tuple[str, ...] = ("instagram", "tiktok", "youtube"),
    ) -> dict:
        """One reel to Instagram, TikTok and YouTube Shorts: three createPost
        calls, because Buffer takes one channel per call.

        Cover frame: `VideoAssetInput.thumbnailUrl` is valid in the schema but
        rejected at runtime ("social networks do not accept custom video
        thumbnail images"). The working option is `metadata.thumbnailOffset`,
        and only for Instagram and TikTok, so the YouTube asset goes without
        it. YouTube has no Shorts flag in Buffer's schema: it infers a Short
        from a vertical video under 60 s.
        """
        channels = self.load_channels()
        plain = {"video": {"url": video_url}}
        with_cover = {"video": {"url": video_url}}
        if thumbnail_offset_ms is not None:
            with_cover["video"]["metadata"] = {"thumbnailOffset": thumbnail_offset_ms}

        per_network = {
            "instagram": ([with_cover], {"instagram": {"type": "reel", "shouldShareToFeed": True}}),
            "tiktok": ([with_cover], {"tiktok": {"title": tiktok_title}}),
            # categoryId became mandatory server side at some point; "22" is
            # YouTube's own "People & Blogs" id, configurable per account.
            "youtube": (
                [plain],
                {"youtube": {"title": youtube_title, "privacy": "public", "madeForKids": False,
                             "categoryId": self.cfg.youtube_category_id}},
            ),
        }
        results: dict = {}
        for network in networks:
            assets, metadata = per_network[network]
            results[network] = self.create_post(
                channels[network], text, assets, metadata=metadata, due_at=due_at, save_to_draft=save_to_draft
            )
        # Drafts never reach an audience; logging them would only add noise.
        if video_name and not save_to_draft:
            self.log_publish(video_name, due_at, results)
        return results

    def publish_carousel(
        self,
        text: str,
        image_urls: list[str],
        tiktok_title: str,
        due_at: str | None = None,
        save_to_draft: bool = False,
    ) -> dict:
        """Instagram and TikTok photo carousel. Instagram has no "carousel"
        type in Buffer ("Instagram does not support the 'carousel' post
        type"): it is type "post" with several image assets."""
        channels = self.load_channels()
        assets = [{"image": {"url": u}} for u in image_urls]
        return {
            "instagram": self.create_post(
                channels["instagram"], text, assets,
                metadata={"instagram": {"type": "post", "shouldShareToFeed": True}},
                due_at=due_at, save_to_draft=save_to_draft,
            ),
            "tiktok": self.create_post(
                channels["tiktok"], text, assets,
                metadata={"tiktok": {"title": tiktok_title}},
                due_at=due_at, save_to_draft=save_to_draft,
            ),
        }

    def log_publish(self, video_name: str, due_at: str | None, results: dict) -> None:
        """Appends video -> scheduled time -> post ids to publish_log.csv.

        Buffer never returns Instagram's final permalink, so due_at is the
        join key to match each local file with its reel in the analytics
        export later (e.g. to measure reach per music track). Never raises: a
        logging failure must not lose a post that is already scheduled.
        """
        try:
            path = self.cfg.publish_log
            path.parent.mkdir(parents=True, exist_ok=True)
            is_new = not path.exists()
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if is_new:
                    writer.writerow(["date", "video", "due_at_utc", "ig_post_id", "tk_post_id", "yt_post_id"])
                writer.writerow([
                    datetime.date.today().isoformat(), video_name, due_at or "",
                    (results.get("instagram") or {}).get("id", ""),
                    (results.get("tiktok") or {}).get("id", ""),
                    (results.get("youtube") or {}).get("id", ""),
                ])
        except Exception as exc:  # noqa: BLE001 -- logging is best effort
            print(f"[warn] could not write {self.cfg.publish_log}: {exc}")


def _unwrap(result: dict, op: str) -> dict:
    if result["__typename"] != "PostActionSuccess":
        raise BufferError(f"{op} failed ({result['__typename']}): {result.get('message')}")
    return result["post"]
