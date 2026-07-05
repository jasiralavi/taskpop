from __future__ import annotations

import ast
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

try:
    from .db import Config, Task, TaskDB, TaskList, xdg_config_dir
    from .google_sync import GoogleSync, GoogleSyncError
except ImportError:
    # Allow running as a plain script from the source tree.
    from db import Config, Task, TaskDB, TaskList, xdg_config_dir
    from google_sync import GoogleSync, GoogleSyncError

APP_ID = "com.dsynz.TaskPop"
APP_VERSION = "v23"

COMMANDS: list[tuple[str, str]] = [
    (":list <name>", "Create a new list"),
    (":unlist", "Remove the current local list"),
    (":shortcut <binding>", "Change the global shortcut"),
    (":google", "Connect Google Tasks"),
    (":sync", "Sync Google Tasks"),
    (":local", "Switch to local-only mode"),
]


class TaskPopWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, db: TaskDB, config: Config) -> None:
        super().__init__(application=app)
        self.db = db
        self.config = config
        self.completed_visible: set[str] = set()
        self.current_filter = ""
        self.lists: list[TaskList] = []
        self.current_list: TaskList | None = None
        self.selected_index = 0
        self.pending_action: str | None = None
        self.default_placeholder = "Type to filter · Ctrl+Enter to add"
        self.task_rows: list[tuple[Task, Gtk.ListBoxRow]] = []
        self.google_sync = GoogleSync(self.db, self.config, self.set_status)

        self.set_title(f"TaskPop {APP_VERSION}")
        self.set_icon_name("taskpop")
        self.set_default_size(520, 520)
        self.set_resizable(False)
        self.add_css()

        self.stack = Gtk.Stack()
        self.set_child(self.stack)

        self.setup_view = self.build_setup_view()
        self.task_view = self.build_task_view()
        self.stack.add_named(self.setup_view, "setup")
        self.stack.add_named(self.task_view, "tasks")

        self.init_key_controller()
        self.refresh_lists()
        self.route_initial_screen()

    def add_css(self) -> None:
        css = b"""
        window { background: #111; }
        .taskpop-root { padding: 14px; }
        .search-entry { font-size: 20px; padding: 10px; }
        .list-title { font-weight: 700; font-size: 14px; opacity: .85; }
        .task-row { padding: 10px 12px; border-radius: 8px; }
        .task-row-active { background: rgba(255,255,255,.12); }
        .task-title { font-size: 17px; }
        .task-title-completed { text-decoration-line: line-through; opacity: .55; }
        .status { opacity: .65; font-size: 12px; }
        .setup-title { font-size: 24px; font-weight: 700; }
        .setup-copy { opacity: .75; }
        .setup-button { padding: 12px; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def build_setup_view(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.add_css_class("taskpop-root")
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(30)
        box.set_margin_bottom(30)
        box.set_margin_start(30)
        box.set_margin_end(30)

        title = Gtk.Label(label="TaskPop Setup")
        title.add_css_class("setup-title")
        title.set_wrap(True)
        box.append(title)

        copy = Gtk.Label(label="Choose how you want to use your tasks.")
        copy.add_css_class("setup-copy")
        copy.set_wrap(True)
        box.append(copy)

        local_btn = Gtk.Button(label="Use locally only")
        local_btn.add_css_class("setup-button")
        local_btn.connect("clicked", self.on_choose_local)
        box.append(local_btn)

        google_btn = Gtk.Button(label="Sync with Google Tasks")
        google_btn.add_css_class("setup-button")
        google_btn.connect("clicked", self.on_choose_google)
        box.append(google_btn)

        note = Gtk.Label(
            label="You can change this later. Local mode needs no login. Google sync uses your browser after the OAuth client file is available."
        )
        note.add_css_class("status")
        note.set_wrap(True)
        box.append(note)

        return box

    def build_task_view(self) -> Gtk.Widget:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.add_css_class("taskpop-root")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        settings_btn = Gtk.Button(label="⚙")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", self.show_settings_dialog)
        top.append(settings_btn)

        self.list_label = Gtk.Label(label="")
        self.list_label.add_css_class("list-title")
        self.list_label.set_xalign(0)
        self.list_label.set_hexpand(True)
        top.append(self.list_label)

        self.sync_label = Gtk.Label(label="")
        self.sync_label.add_css_class("status")
        top.append(self.sync_label)
        root.append(top)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(self.default_placeholder)
        self.entry.add_css_class("search-entry")
        self.entry.connect("changed", self.on_filter_changed)
        # Plain Enter should not add tasks. Ctrl+Enter is handled by the key controller.
        root.append(self.entry)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        # Keep keyboard focus in the filter entry. We manage the highlighted
        # row ourselves instead of letting Gtk.ListBox move focus to rows.
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_focusable(False)
        scroller.set_child(self.listbox)
        root.append(scroller)

        hints = Gtk.Label(label="↑/↓ navigate · Space complete/uncomplete · Ctrl+Tab switch list · Esc close")
        hints.add_css_class("status")
        hints.set_xalign(0)
        root.append(hints)
        return root

    def init_key_controller(self) -> None:
        controller = Gtk.EventControllerKey()
        # Capture lets TaskPop handle Ctrl+Enter, Ctrl+Tab, Esc, and arrows
        # before Gtk.Entry consumes them, while normal typing still reaches the entry.
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(controller)

    def route_initial_screen(self) -> None:
        mode = self.config.get("mode")
        if not mode:
            self.stack.set_visible_child_name("setup")
        else:
            self.stack.set_visible_child_name("tasks")
            self.load_last_list()
            self.refresh_tasks()
            self.ensure_first_run_shortcut()
            self.set_startup_status()
            if self.config.get("sync_mode") == "google":
                self.sync_in_background(interactive=False)

    def on_choose_local(self, button: Gtk.Button) -> None:
        self.enable_local_mode()

    def on_choose_google(self, button: Gtk.Button) -> None:
        self.enable_google_mode(interactive=True)

    def enable_local_mode(self) -> None:
        self.config.set("mode", "local")
        self.config.set("sync_mode", "none")
        self.stack.set_visible_child_name("tasks")
        self.load_last_list()
        self.refresh_tasks()
        self.set_status(f"{APP_VERSION} · Local only")
        self.ensure_first_run_shortcut()
        self.focus_entry()

    def enable_google_mode(self, interactive: bool = True) -> None:
        self.config.set("mode", "local_first")
        self.config.set("sync_mode", "google")
        self.stack.set_visible_child_name("tasks")
        self.load_last_list()
        self.refresh_tasks()
        self.ensure_first_run_shortcut()
        if not self.google_sync.has_client_secret():
            self.set_status("Google setup needed · config folder opened")
            self.open_google_setup_location()
        else:
            self.connect_google_in_background(interactive=interactive)
        self.focus_entry()

    def show_settings_dialog(self, button: Gtk.Button | None = None) -> None:
        dialog = Gtk.Dialog(title="TaskPop Settings", transient_for=self, modal=True)
        dialog.set_default_size(460, 380)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        title = Gtk.Label(label="Settings")
        title.add_css_class("setup-title")
        title.set_xalign(0)
        content.append(title)

        mode_text = "Google Tasks sync" if self.config.get("sync_mode") == "google" else "Local only"
        mode = Gtk.Label(label=f"Current mode: {mode_text}")
        mode.set_xalign(0)
        content.append(mode)

        local_btn = Gtk.Button(label="Use local only")
        local_btn.set_tooltip_text("Stop Google sync and keep using the local database.")
        local_btn.connect("clicked", lambda *_: self._settings_local(dialog))
        content.append(local_btn)

        google_btn = Gtk.Button(label="Connect Google Tasks")
        google_btn.set_tooltip_text("Open browser login if OAuth is ready, or open the setup folder.")
        google_btn.connect("clicked", lambda *_: self._settings_google(dialog))
        content.append(google_btn)

        sync_btn = Gtk.Button(label="Sync now")
        sync_btn.set_tooltip_text("Sync with Google Tasks.")
        sync_btn.connect("clicked", lambda *_: self._settings_sync_now(dialog))
        content.append(sync_btn)

        new_list_btn = Gtk.Button(label="Create new local list")
        new_list_btn.set_tooltip_text("Use the main input field to create the list.")
        new_list_btn.connect("clicked", lambda *_: self._settings_new_list(dialog))
        content.append(new_list_btn)

        shortcut_btn = Gtk.Button(label="Change global shortcut")
        shortcut_btn.set_tooltip_text("Use the main input field to set the GNOME shortcut.")
        shortcut_btn.connect("clicked", lambda *_: self._settings_shortcut(dialog))
        content.append(shortcut_btn)

        config_btn = Gtk.Button(label="Open config folder")
        config_btn.connect("clicked", lambda *_: self.open_config_folder())
        content.append(config_btn)

        oauth_btn = Gtk.Button(label="Open Google OAuth setup guide")
        oauth_btn.connect("clicked", lambda *_: self.open_google_setup_guide())
        content.append(oauth_btn)

        info = Gtk.Label(
            label=(
                "Shortcuts: Ctrl+Enter adds · Up/Down navigate · Space completes "
                "when the filter is empty · Ctrl+Tab switches lists · Esc closes. "
                "Config actions use the main input field."
            )
        )
        info.add_css_class("status")
        info.set_wrap(True)
        info.set_xalign(0)
        content.append(info)

        path = Gtk.Label(label=f"Config: {xdg_config_dir()}")
        path.add_css_class("status")
        path.set_selectable(True)
        path.set_wrap(True)
        path.set_xalign(0)
        content.append(path)

        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _settings_local(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.enable_local_mode()

    def _settings_google(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        GLib.idle_add(lambda: (self.start_google_setup_flow(), False)[1])

    def _settings_sync_now(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        GLib.idle_add(lambda: (self.start_sync_now_flow(), False)[1])

    def _settings_new_list(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        GLib.idle_add(lambda: (self.start_new_list_flow(), False)[1])

    def _settings_shortcut(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        GLib.idle_add(lambda: (self.start_shortcut_flow(), False)[1])

    def start_new_list_flow(self) -> None:
        self.pending_action = "new_list"
        self.entry.set_text("")
        self.entry.set_placeholder_text("New list name · Ctrl+Enter to create")
        self.set_status("Type new list name, then press Ctrl+Enter")
        self.focus_entry()

    def start_shortcut_flow(self) -> None:
        self.pending_action = "shortcut"
        self.entry.set_text("")
        current = self.config.get("shortcut_binding", "<Super>t")
        self.entry.set_placeholder_text(f"Shortcut binding · Current: {current}")
        self.set_status("Type shortcut, for example <Super>t, then press Ctrl+Enter")
        self.focus_entry()

    def start_google_setup_flow(self) -> None:
        self.pending_action = None
        self.entry.set_text("")
        self.entry.set_placeholder_text(self.default_placeholder)
        self.config.set("mode", "local_first")
        self.config.set("sync_mode", "google")

        if not self.google_sync.has_client_secret():
            self.set_status("Add google_client_secret.json · config folder opened")
            self.open_google_setup_location()
            return

        self.set_status("Opening browser for Google login…")
        self.connect_google_in_background(interactive=True)

    def start_sync_now_flow(self) -> None:
        self.pending_action = None
        self.entry.set_text("")
        self.entry.set_placeholder_text(self.default_placeholder)

        if self.config.get("sync_mode") != "google":
            self.set_status("Google sync not enabled")
            return

        if not self.google_sync.has_client_secret():
            self.set_status("Add google_client_secret.json · config folder opened")
            self.open_google_setup_location()
            return

        self.set_status("Syncing…")
        self.connect_google_in_background(interactive=True)

    def clear_pending_action(self) -> None:
        self.pending_action = None
        self.entry.set_text("")
        self.entry.set_placeholder_text(self.default_placeholder)
        self.focus_entry()

    def show_new_list_dialog(self) -> None:
        dialog = Gtk.Dialog(title="New List", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Create", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        label = Gtk.Label(label="List name")
        label.set_xalign(0)
        content.append(label)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Example: Work, Personal, Today")
        entry.connect("activate", lambda e: dialog.response(Gtk.ResponseType.OK))
        content.append(entry)

        def on_response(d: Gtk.Dialog, response: int) -> None:
            if response == Gtk.ResponseType.OK:
                title = entry.get_text().strip()
                if title:
                    list_id = self.db.create_list(title, last_used=True)
                    self.current_list = self.db.get_list(list_id)
                    self.refresh_lists()
                    self.update_list_label()
                    self.entry.set_text("")
                    self.refresh_tasks()
                    self.set_status("List created")
                    self.focus_entry()
            d.destroy()

        dialog.connect("response", on_response)
        dialog.present()
        GLib.idle_add(lambda: entry.grab_focus() or False)

    def open_config_folder(self) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(xdg_config_dir().as_uri(), None)
        except Exception as exc:
            self.set_status("Could not open config folder")
            print(f"TaskPop open config folder failed: {exc}", file=sys.stderr)

    def set_startup_status(self) -> None:
        if self.config.get("sync_mode") == "google":
            if self.google_sync.has_client_secret():
                self.set_status(f"{APP_VERSION} · Google ready")
            else:
                self.set_status(f"{APP_VERSION} · Google setup needed")
        else:
            self.set_status(f"{APP_VERSION} · Local mode")

    def ensure_first_run_shortcut(self) -> None:
        if self.config.get("shortcut_initialized"):
            return
        ok, message = self.configure_global_shortcut(self.config.get("shortcut_binding", "<Super>t"))
        self.config.set("shortcut_initialized", True)
        self.set_status(message if ok else "Shortcut not set")

    def configure_global_shortcut(self, binding: str) -> tuple[bool, str]:
        binding = binding.strip() or "<Super>t"
        key_path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/taskpop/"
        command = str(Path.home() / ".local" / "bin" / "taskpop")
        base_schema = "org.gnome.settings-daemon.plugins.media-keys"
        custom_schema = f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{key_path}"

        try:
            current = subprocess.check_output(
                ["gsettings", "get", base_schema, "custom-keybindings"],
                text=True,
                stderr=subprocess.STDOUT,
            ).strip()
            raw = current.replace("@as ", "")
            try:
                items = ast.literal_eval(raw)
                if not isinstance(items, list):
                    items = []
            except Exception:
                items = []
            if key_path not in items:
                items.append(key_path)
            list_value = "[" + ", ".join(repr(item) for item in items) + "]"
            subprocess.run(["gsettings", "set", base_schema, "custom-keybindings", list_value], check=True)
            subprocess.run(["gsettings", "set", custom_schema, "name", "TaskPop"], check=True)
            subprocess.run(["gsettings", "set", custom_schema, "command", command], check=True)
            subprocess.run(["gsettings", "set", custom_schema, "binding", binding], check=True)
            self.config.set("shortcut_binding", binding)
            return True, f"Shortcut set: {binding}"
        except FileNotFoundError:
            return False, "gsettings not found"
        except Exception as exc:
            print(f"TaskPop shortcut setup failed: {exc}", file=sys.stderr)
            return False, "Shortcut setup failed"

    def open_google_setup_location(self) -> None:
        self.write_google_setup_guide()
        self.open_config_folder()

    def write_google_setup_guide(self) -> Path:
        guide = xdg_config_dir() / "GOOGLE_SETUP.md"
        secret = xdg_config_dir() / "google_client_secret.json"
        guide.write_text(
            "# TaskPop Google Tasks setup\n\n"
            "TaskPop can open the browser login automatically after the OAuth client file is available.\n\n"
            "1. Go to Google Cloud Console.\n"
            "2. Create or select a project.\n"
            "3. Enable Google Tasks API.\n"
            "4. Configure OAuth consent screen. For personal use, External + Testing is fine.\n"
            "5. Add your Gmail as a test user.\n"
            "6. Create OAuth Client ID → Desktop app.\n"
            "7. Download the JSON file.\n"
            f"8. Save/rename it exactly as: `{secret}`\n\n"
            "Then open TaskPop → Settings → Connect Google Tasks.\n",
            encoding="utf-8",
        )
        return guide

    def open_google_setup_guide(self) -> None:
        guide = self.write_google_setup_guide()
        try:
            Gio.AppInfo.launch_default_for_uri(guide.as_uri(), None)
            self.set_status("Opened Google setup guide")
        except Exception as exc:
            self.set_status(f"Guide: {guide}")
            print(f"TaskPop open guide failed: {exc}", file=sys.stderr)

    def show_google_help_dialog(self) -> None:
        path = xdg_config_dir() / "google_client_secret.json"
        self.set_status(f"Google setup needed: {path}")
        self.open_google_setup_location()

    def refresh_lists(self) -> None:
        self.lists = self.db.list_lists()

    def load_last_list(self) -> None:
        self.refresh_lists()
        self.current_list = self.db.get_last_list()
        self.update_list_label()

    def update_list_label(self) -> None:
        if not self.current_list:
            self.list_label.set_text("No list")
            return
        index = next((i for i, l in enumerate(self.lists) if l.id == self.current_list.id), 0) + 1
        self.list_label.set_text(f"{self.current_list.title}  ·  {index}/{max(len(self.lists), 1)}")

    def on_filter_changed(self, entry: Gtk.Entry) -> None:
        # Do not grab focus or change cursor position here.
        # In GTK this can select the whole entry after every refresh,
        # causing the next typed character to replace the previous text.
        self.current_filter = entry.get_text()
        self.refresh_tasks(keep_selection=True)

    def add_from_entry(self) -> None:
        text = self.entry.get_text().strip()

        if self.pending_action == "new_list":
            if not text:
                return
            list_id = self.db.create_list(text, last_used=True)
            self.current_list = self.db.get_list(list_id)
            self.refresh_lists()
            self.update_list_label()
            self.clear_pending_action()
            self.refresh_tasks()
            self.set_status(f"List created: {text}")
            return

        if self.pending_action == "shortcut":
            if not text:
                return
            ok, message = self.configure_global_shortcut(text)
            self.clear_pending_action()
            self.set_status(message)
            return

        if text.startswith(":list "):
            name = text[6:].strip()
            if name:
                list_id = self.db.create_list(name, last_used=True)
                self.current_list = self.db.get_list(list_id)
                self.refresh_lists()
                self.update_list_label()
                self.entry.set_text("")
                self.refresh_tasks()
                self.set_status(f"List created: {name}")
            return

        if text.startswith(":shortcut "):
            binding = text[len(":shortcut "):].strip()
            if binding:
                ok, message = self.configure_global_shortcut(binding)
                self.entry.set_text("")
                self.set_status(message)
            return

        if text == ":unlist":
            self.remove_current_list()
            return

        if text == ":google":
            self.start_google_setup_flow()
            return

        if text == ":sync":
            self.start_sync_now_flow()
            return

        if text == ":local":
            self.enable_local_mode()
            return

        if text.startswith(":"):
            self.set_status("Unknown command. Type : to see commands.")
            return

        if not text or not self.current_list:
            return

        self.db.add_task(self.current_list.id, text)
        self.entry.set_text("")
        self.refresh_tasks()
        if self.config.get("sync_mode") == "google":
            self.connect_google_in_background(interactive=False)

    def remove_current_list(self) -> None:
        if not self.current_list:
            return

        self.refresh_lists()
        if len(self.lists) <= 1:
            self.entry.set_text("")
            self.set_status("Cannot remove the only list")
            return

        if self.current_list.google_list_id:
            self.entry.set_text("")
            self.set_status("Cannot remove Google-synced lists locally yet")
            return

        removed_title = self.current_list.title
        removed_id = self.current_list.id
        self.db.delete_list(removed_id)
        self.refresh_lists()

        self.current_list = next((lst for lst in self.lists if lst.id != removed_id), None)
        if self.current_list:
            self.db.set_last_list(self.current_list.id)
        else:
            self.current_list = self.db.get_last_list()

        self.entry.set_text("")
        self.completed_visible.clear()
        self.update_list_label()
        self.refresh_tasks()
        self.set_status(f"Removed list: {removed_title}")

    def refresh_tasks(self, keep_selection: bool = False) -> None:
        if not self.current_list:
            return

        if self.current_filter.startswith(":"):
            self.show_command_rows(self.current_filter)
            return
        old_index = self.selected_index if keep_selection else 0
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)
        self.task_rows = []
        tasks = self.db.list_tasks(self.current_list.id, self.completed_visible, self.current_filter)
        for task in tasks:
            row = self.make_task_row(task)
            self.listbox.append(row)
            self.task_rows.append((task, row))
        if self.task_rows:
            self.selected_index = min(old_index, len(self.task_rows) - 1)
            self.apply_selection_style()
        else:
            self.selected_index = 0

    def show_command_rows(self, query: str) -> None:
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)

        self.task_rows = []
        q = query.strip().lower()
        matches = []
        for command, description in COMMANDS:
            command_l = command.lower()
            description_l = description.lower()
            if q in (":", "") or command_l.startswith(q) or q in description_l:
                matches.append((command, description))

        if not matches:
            matches = [("No matching command", "Commands start with : and cannot be added as tasks")]

        for command, description in matches:
            self.listbox.append(self.make_command_row(command, description))

        self.selected_index = 0
        self.set_status("Command mode · Ctrl+Enter runs a command")

    def make_command_row(self, command: str, description: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("task-row")
        row.set_focusable(False)
        row.set_selectable(False)
        row.set_activatable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        title = Gtk.Label(label=command)
        title.set_xalign(0)
        title.add_css_class("task-title")
        box.append(title)

        desc = Gtk.Label(label=description)
        desc.set_xalign(0)
        desc.add_css_class("status")
        desc.set_wrap(True)
        box.append(desc)

        row.set_child(box)
        return row

    def make_task_row(self, task: Task) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("task-row")
        row.set_focusable(False)
        row.set_selectable(False)
        row.set_activatable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mark = "☑" if task.status == "completed" else "☐"
        check = Gtk.Label(label=mark)
        check.set_width_chars(2)
        box.append(check)
        title = Gtk.Label(label=task.title)
        title.set_xalign(0)
        title.set_wrap(True)
        title.set_hexpand(True)
        title.add_css_class("task-title")
        if task.status == "completed":
            title.add_css_class("task-title-completed")
        box.append(title)
        if task.is_dirty:
            dirty = Gtk.Label(label="•")
            dirty.set_tooltip_text("Pending sync")
            box.append(dirty)
        row.set_child(box)
        return row

    def on_key_pressed(self, controller, keyval, keycode, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if keyval == Gdk.KEY_Escape:
            if self.pending_action:
                self.clear_pending_action()
                self.set_status("Cancelled")
                return True
            self.hide_popup()
            return True

        if self.stack.get_visible_child_name() != "tasks":
            return False

        if ctrl and keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.add_from_entry()
            return True

        if ctrl and keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.switch_list(-1 if shift or keyval == Gdk.KEY_ISO_Left_Tab else 1)
            return True

        if keyval == Gdk.KEY_Down:
            self.move_selection(1)
            return True

        if keyval == Gdk.KEY_Up:
            self.move_selection(-1)
            return True

        # Space toggles the selected task only when the filter box is empty.
        # If text is being typed, a space should remain normal text input.
        if keyval == Gdk.KEY_space and not self.entry.get_text():
            self.toggle_selected_task()
            return True

        return False

    def apply_selection_style(self) -> None:
        for index, (_task, row) in enumerate(self.task_rows):
            if index == self.selected_index:
                row.add_css_class("task-row-active")
            else:
                row.remove_css_class("task-row-active")

    def move_selection(self, delta: int) -> None:
        if not self.task_rows:
            return
        self.selected_index = max(0, min(len(self.task_rows) - 1, self.selected_index + delta))
        self.apply_selection_style()
        self.refocus_entry_end()

    def toggle_selected_task(self) -> None:
        if not self.task_rows:
            return
        task, _row = self.task_rows[self.selected_index]
        new_status = self.db.toggle_task(task.id)
        if new_status == "completed":
            self.completed_visible.add(task.id)
        else:
            self.completed_visible.discard(task.id)
        self.refresh_tasks(keep_selection=True)
        if self.config.get("sync_mode") == "google":
            self.sync_in_background(interactive=False)

    def switch_list(self, delta: int) -> None:
        self.refresh_lists()
        if not self.lists:
            return
        if not self.current_list:
            self.current_list = self.lists[0]
        current_idx = next((i for i, l in enumerate(self.lists) if l.id == self.current_list.id), 0)
        next_idx = (current_idx + delta) % len(self.lists)
        self.current_list = self.lists[next_idx]
        self.db.set_last_list(self.current_list.id)
        self.completed_visible.clear()
        self.entry.set_text("")
        self.update_list_label()
        self.refresh_tasks()

    def focus_entry(self) -> None:
        def _focus():
            if hasattr(self.entry, "grab_focus_without_selecting"):
                self.entry.grab_focus_without_selecting()
            else:
                self.entry.grab_focus()
            self.entry.set_position(-1)
            return False
        GLib.idle_add(_focus)

    def refocus_entry_end(self) -> None:
        def _focus():
            if hasattr(self.entry, "grab_focus_without_selecting"):
                self.entry.grab_focus_without_selecting()
            else:
                self.entry.grab_focus()
            self.entry.set_position(-1)
            return False
        GLib.idle_add(_focus)

    def show_popup(self) -> None:
        self.completed_visible.clear()
        self.refresh_lists()
        self.load_last_list()
        self.refresh_tasks()
        self.present()
        self.focus_entry()

    def hide_popup(self) -> None:
        self.completed_visible.clear()
        self.pending_action = None
        self.entry.set_placeholder_text(self.default_placeholder)
        self.entry.set_text("")
        app = self.get_application()
        if app:
            app.quit()
        else:
            self.set_visible(False)

    def set_status(self, text: str) -> None:
        def _set():
            self.sync_label.set_text(text)
            return False
        GLib.idle_add(_set)

    def sync_in_background(self, interactive: bool = False) -> None:
        self.connect_google_in_background(interactive=interactive)

    def connect_google_in_background(self, interactive: bool = False) -> None:
        def work():
            worker_db = None
            try:
                if interactive:
                    self.set_status("Opening browser for Google login…")

                # SQLite connections are thread-bound by default.
                # The UI owns self.db, so the sync thread must open its own
                # TaskDB connection instead of using the UI connection.
                worker_db = TaskDB(self.db.path)
                worker_sync = GoogleSync(worker_db, self.config, self.set_status)
                worker_sync.sync(interactive=interactive)

                GLib.idle_add(self.after_sync_refresh)

            except GoogleSyncError as exc:
                if "Missing OAuth client file" in str(exc):
                    self.set_status("Add google_client_secret.json · config folder opened")
                    GLib.idle_add(lambda: (self.open_google_setup_location(), False)[1])
                elif "Google login is required" in str(exc):
                    self.set_status("Google login required")
                else:
                    self.set_status("Google sync not connected")
                print(f"TaskPop Google sync: {exc}", file=sys.stderr)

            except Exception as exc:
                pending = 0
                try:
                    if worker_db is not None:
                        pending = worker_db.count_dirty()
                except Exception:
                    pending = 0
                self.set_status(f"Offline · {pending} pending" if pending else "Sync failed")
                print(f"TaskPop sync failed: {exc}", file=sys.stderr)

            finally:
                try:
                    if worker_db is not None:
                        worker_db.conn.close()
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def after_sync_refresh(self):
        self.refresh_lists()
        if self.current_list:
            # Keep the same list if it still exists.
            self.current_list = self.db.get_list(self.current_list.id) or self.db.get_last_list()
        else:
            self.current_list = self.db.get_last_list()
        self.update_list_label()
        self.refresh_tasks(keep_selection=True)
        return False


class TaskPopApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: TaskPopWindow | None = None
        self.db = TaskDB()
        self.config = Config()

    def do_activate(self) -> None:
        if self.window is None:
            self.window = TaskPopWindow(self, self.db, self.config)
            self.window.connect("close-request", self.on_close_request)
            self.window.show_popup()
            return

        if self.window.is_visible():
            self.window.hide_popup()
        else:
            self.window.show_popup()

    def on_close_request(self, window) -> bool:
        window.hide_popup()
        return True


def main(argv: list[str] | None = None) -> int:
    app = TaskPopApp()
    return app.run(argv or sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
