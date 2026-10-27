"""Google Drive as free media hosting for the publishing step.

Schedulers like Buffer and Metricool take the media as a public URL. Instead
of depending on each one having its own Google Drive integration linked, the
pipeline uploads the final file with the official Drive API, grants "anyone
with the link" read access and hands over the direct-download URL.

Uses the official API (not browser automation) because it writes to a real
account: the API is the path with no risk of tripping anti-bot checks.

Google client libraries are imported inside the functions so the rest of the
package (and its tests) does not need them installed.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config

# drive.file only sees files this app created. drive.readonly is there for
# reading files the user drops in by hand (e.g. new music tracks). Changing
# the scopes invalidates an existing token.json: delete it and authorize again.
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]
FOLDER_MIME = "application/vnd.google-apps.folder"

MIME_TYPES = {
    ".mp4": "video/mp4",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
}


class DriveAuthError(RuntimeError):
    pass


def get_credentials(cfg: Config, interactive: bool = True):
    """Loads token.json and refreshes it if needed.

    With interactive=False (cron jobs, preflight) it never opens a browser: an
    unattended run cannot sit waiting for a consent screen, so it raises
    DriveAuthError with the fix instead.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if cfg.drive_token.exists():
        creds = Credentials.from_authorized_user_file(str(cfg.drive_token), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactive:
        if not cfg.drive_credentials.exists():
            raise DriveAuthError(f"missing OAuth client file: {cfg.drive_credentials}")
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.drive_credentials), SCOPES)
        creds = flow.run_local_server(port=0)
    else:
        raise DriveAuthError("no valid token.json; run `reels-autopublish drive-login` once")
    cfg.drive_token.parent.mkdir(parents=True, exist_ok=True)
    cfg.drive_token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_service(cfg: Config, interactive: bool = True):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=get_credentials(cfg, interactive))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_folder(service, name: str, parent_id: str | None = None) -> str | None:
    query = f"name = '{_escape(name)}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    files = service.files().list(q=query, fields="files(id, name)").execute().get("files", [])
    return files[0]["id"] if files else None


def get_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    folder_id = find_folder(service, name, parent_id)
    if folder_id:
        return folder_id
    metadata = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        metadata["parents"] = [parent_id]
    return service.files().create(body=metadata, fields="id").execute()["id"]


def upload_file(service, folder_id: str, path: Path) -> dict:
    from googleapiclient.http import MediaFileUpload

    mime_type = MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")
    media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
    return (
        service.files()
        .create(body={"name": path.name, "parents": [folder_id]}, media_body=media, fields="id, webViewLink")
        .execute()
    )


def direct_link(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def make_public(service, file_id: str) -> str:
    """Grants "anyone with the link" read access and returns a direct-download
    URL any HTTP client can fetch without auth. Only call it on media that is
    about to go public on social media anyway, never on drafts or source
    material."""
    service.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
    return direct_link(file_id)


def trash_by_name(service, folder_id: str | None, name: str) -> list[str]:
    """Moves matching files to Drive's trash (recoverable for 30 days) rather
    than deleting them: cleanup runs unattended, and a wrong date or name
    should never be able to destroy something for good."""
    if not folder_id:
        return []
    query = f"name = '{_escape(name)}' and '{folder_id}' in parents and trashed = false"
    trashed = []
    for f in service.files().list(q=query, fields="files(id, name)").execute().get("files", []):
        service.files().update(fileId=f["id"], body={"trashed": True}).execute()
        trashed.append(f["id"])
    return trashed


def trash_folder(service, parent_id: str | None, name: str) -> str | None:
    folder_id = find_folder(service, name, parent_id)
    if folder_id:
        service.files().update(fileId=folder_id, body={"trashed": True}).execute()
    return folder_id


def upload_and_publish(cfg: Config, paths: list[Path], folder_name: str | None = None) -> list[dict]:
    """Uploads files to one Drive folder. Files whose suffix is in
    `drive.public_suffixes` also get a public direct link, ready to pass to
    the scheduler."""
    service = get_service(cfg)
    folder_id = get_or_create_folder(service, folder_name or cfg.drive_video_folder)
    results = []
    for path in paths:
        uploaded = upload_file(service, folder_id, path)
        entry = {"name": path.name, "id": uploaded["id"], "view": uploaded.get("webViewLink")}
        if path.suffix.lower() in cfg.drive_public_suffixes:
            entry["public_url"] = make_public(service, uploaded["id"])
        results.append(entry)
    return results
