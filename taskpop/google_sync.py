from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    from .db import Config, TaskDB, xdg_config_dir
except ImportError:
    from db import Config, TaskDB, xdg_config_dir

SCOPES = ["https://www.googleapis.com/auth/tasks"]


class GoogleSyncError(Exception):
    pass


class GoogleSync:
    """Small Google Tasks sync adapter.

    The app works without this module being usable. Google sync needs:
      - google-api-python-client
      - google-auth-oauthlib
      - a desktop OAuth client JSON saved as ~/.config/taskpop/google_client_secret.json
    """

    def __init__(self, db: TaskDB, config: Config, status_cb: Callable[[str], None] | None = None) -> None:
        self.db = db
        self.config = config
        self.status_cb = status_cb or (lambda msg: None)
        self.config_dir = xdg_config_dir()
        self.client_secret_path = self.config_dir / "google_client_secret.json"
        self.token_path = self.config_dir / "google_token.json"
        self.service = None

    def _import_google_libs(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except Exception as exc:  # pragma: no cover
            raise GoogleSyncError(
                "Google sync packages are not installed. Run the installer or install requirements.txt."
            ) from exc
        return Request, Credentials, InstalledAppFlow, build

    def has_client_secret(self) -> bool:
        return self.client_secret_path.exists()

    def authorize(self, interactive: bool = True):
        Request, Credentials, InstalledAppFlow, build = self._import_google_libs()

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            elif interactive:
                if not self.client_secret_path.exists():
                    raise GoogleSyncError(
                        f"Missing OAuth client file: {self.client_secret_path}\n"
                        "Create a Google Cloud Desktop OAuth client and save it there."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secret_path), SCOPES)
                self.status_cb("Opening browser for Google login…")
                creds = flow.run_local_server(port=0, open_browser=True)
            else:
                raise GoogleSyncError("Google login is required.")

            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        self.service = build("tasks", "v1", credentials=creds)
        self.config.set("sync_mode", "google")
        return self.service

    def sync(self, interactive: bool = False) -> None:
        self.status_cb("Syncing…")
        service = self.service or self.authorize(interactive=interactive)
        self.pull(service)
        self.push_dirty(service)
        dirty = self.db.count_dirty()
        self.status_cb("Synced" if dirty == 0 else f"{dirty} changes pending")

    def pull(self, service) -> None:
        token = None
        while True:
            result = service.tasklists().list(pageToken=token, maxResults=100).execute()
            for item in result.get("items", []):
                list_id = self.db.upsert_google_list(item.get("title", "Untitled"), item["id"])
                self.pull_tasks_for_list(service, list_id, item["id"])
            token = result.get("nextPageToken")
            if not token:
                break

    def pull_tasks_for_list(self, service, local_list_id: str, google_list_id: str) -> None:
        token = None
        while True:
            result = service.tasks().list(
                tasklist=google_list_id,
                pageToken=token,
                maxResults=100,
                showCompleted=True,
                showHidden=True,
                showDeleted=False,
            ).execute()
            for item in result.get("items", []):
                self.db.upsert_google_task(
                    list_id=local_list_id,
                    title=item.get("title") or "Untitled",
                    google_task_id=item["id"],
                    status=item.get("status", "needsAction"),
                    notes=item.get("notes"),
                    completed_at=item.get("completed"),
                )
            token = result.get("nextPageToken")
            if not token:
                break

    def push_dirty(self, service) -> None:
        for task in self.db.dirty_tasks():
            task_list = self.db.get_list(task.list_id)
            if not task_list:
                continue

            google_list_id = task_list.google_list_id
            if not google_list_id:
                # For local lists, create a matching list in Google on first sync.
                created_list = service.tasklists().insert(body={"title": task_list.title}).execute()
                google_list_id = created_list["id"]
                self.db.conn.execute(
                    "UPDATE lists SET source = 'google', google_list_id = ?, updated_at = datetime('now') WHERE id = ?",
                    (google_list_id, task_list.id),
                )
                self.db.conn.commit()

            body = {
                "title": task.title,
                "notes": task.notes or "",
                "status": task.status,
            }
            if task.status == "completed" and task.completed_at:
                body["completed"] = task.completed_at

            if task.google_task_id:
                service.tasks().patch(
                    tasklist=google_list_id,
                    task=task.google_task_id,
                    body=body,
                ).execute()
                self.db.mark_clean(task.id)
            else:
                created = service.tasks().insert(tasklist=google_list_id, body=body).execute()
                self.db.update_google_task_id(task.id, created["id"])
