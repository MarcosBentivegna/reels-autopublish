# reels-autopublish

The publishing half of a pipeline that ran a faceless Instagram, TikTok and YouTube Shorts account on autopilot: one or more reels a day, generated, rendered, scheduled and cleaned up with no manual steps.

The account reached **11.1K Instagram followers** and **621,789 views in 90 days** (533K of them from reels). This repo holds the parts that are not tied to that account and can run any other one: the content generation (prompts, characters, visual style) stays private.

## What it does

```
 render reel ──► mux ──► upload ──► publish-reel ──► cleanup (next day)
                  │         │            │
            music track  Drive +     Buffer GraphQL:
            rotation     public link Instagram, TikTok, YouTube

 preflight runs first and stops the batch if anything above would fail
```

| Command | What it does |
|---|---|
| `preflight` | Checks tools, disk, state files, a **real test upload to Drive** and that the saved Buffer channel ids still match the live account. Exit code 1 blocks the batch. |
| `mux` | Adds a background track to a silent video. Avoids the last N tracks, trims to the real video length with `ffprobe`, fades in and out, logs which track went into which reel. |
| `upload` | Uploads to Google Drive with the official API and returns a public direct link, so the scheduler does not need its own Drive integration. |
| `publish-reel` | Schedules the reel on Instagram, TikTok and YouTube Shorts through Buffer, and logs `video → time → post ids` to join with analytics later. `--draft` creates drafts that are never sent. |
| `cleanup` | Deletes past days locally and moves their Drive copies to the trash (recoverable for 30 days). Decides by the date in the folder name, not file age. |

## Lessons the code encodes

Each of these broke something on a live account first. They are written down in the docstrings next to the code they shaped.

- **Check by writing, not by authenticating.** A Drive token can refresh fine and still lack write permission. Preflight uploads and deletes a probe file, because a failure at publishing time means the day's videos are already rendered for nothing.
- **Buffer's `editPost` is stricter than its schema.** Text, assets and metadata are marked optional, but a time-only edit of an Instagram post fails validation. And without an explicit `mode`, the call returns success while the scheduled time stays the same.
- **Never test an edit on a real queued post.** A test caption that is not reverted gets published as is. Test with `--draft`, then delete.
- **Custom cover images are rejected at runtime** even though the schema accepts them. The working option is a frame offset, only on Instagram and TikTok.
- **Retention by calendar date, not by age.** A daily job with a "24 hours old" rule keeps a reel rendered at 23:00 for an extra day.
- **Trash, do not delete,** in anything that runs unattended.
- **Why Buffer and not Metricool** for posting: the Metricool plan tested capped publications at 20 a month, below one reel a day on three networks.

## Setup

Requires Python 3.11+ and `ffmpeg`.

```bash
git clone https://github.com/MarcosBentivegna/reels-autopublish
cd reels-autopublish
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

In your content project:

```bash
cp reels.example.toml reels.toml   # every value is optional
mkdir -p secrets tracks
```

1. **Google Drive.** Create an OAuth client of type "Desktop app" in Google Cloud Console, enable the Drive API and save the JSON as `secrets/credentials.json`. While the consent screen is in testing mode, add your Google account as a test user. Then run `reels-autopublish drive-login` once.
2. **Buffer.** Connect the channels in Buffer, put an API token in `secrets/buffer_token.txt` and run `reels-autopublish buffer-channels`.
3. Put your music in `tracks/`.

`secrets/` is gitignored as a whole.

## Daily run

```bash
reels-autopublish preflight || exit 1
reels-autopublish mux output/20261102/videos/silent.mp4 output/20261102/videos/reel.mp4
reels-autopublish upload output/20261102/videos/reel.mp4      # prints public_url
reels-autopublish publish-reel --video-url "$URL" --title "..." \
  --caption-file output/20261102/videos/reel.txt \
  --due-at 2026-11-02T18:00:00Z --cover-ms 4500 --name reel.mp4
```

And once a day from cron or launchd:

```bash
reels-autopublish cleanup
```

On macOS, keep the project outside `~/Documents`, `~/Desktop` and `~/Downloads`: launchd jobs get "Operation not permitted" there, and granting Full Disk Access did not fix it reliably.

## Tests

`pytest` covers config resolution, track rotation, the ffmpeg mux end to end (skipped without ffmpeg), every Buffer request shape against a fake transport, retention dates and the preflight checks. CI runs them on Python 3.11 to 3.13.

## License

MIT
