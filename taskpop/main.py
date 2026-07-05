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
APP_VERSION = "v0.2.0"

COMMANDS: list[tuple[str, str]] = [
    (":list-l <name>", "Create a new local list"),
    (":list-gt <name>", "Create a new Google Tasks list"),
    (":unlist", "Remove the current list after DELETE confirmation"),
    (":rename <New List Name>", "Rename the current list"),
    (":reorder <number>", "Move current list to a new position"),
    (":order-az", "Order lists alphabetically A to Z"),
    (":order-za", "Order lists alphabetically Z to A"),
    (":order-lg", "Order local lists first, then Google Tasks lists"),
    (":order-gl", "Order Google Tasks lists first, then local lists"),
    (":clear", "Clear completed tasks from the current list"),
    (":settings", "Open TaskPop Settings"),
    (":list-c-gt", "Convert current local list to Google Tasks"),
    (":convert-to-google-task", "Convert current local list to Google Tasks"),
    (":list-c-l", "Convert current Google Tasks list to local"),
    (":convert-to-local", "Convert current Google Tasks list to local"),
    (":enable-gt", "Enable Google Tasks lists"),
    (":disable-gt", "Disable Google Tasks lists"),
    (":enable-l", "Enable local lists"),
    (":disable-l", "Disable local lists"),
    (":shortcut <binding>", "Change the global shortcut"),
    (":sync", "Sync Google Tasks"),
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
        self.pending_task_id: str | None = None
        self.default_placeholder = "Type to filter · Ctrl+Enter to add"
        self.task_rows: list[tuple[Task | None, Gtk.ListBoxRow]] = []
        self.command_matches: list[tuple[str, str]] = []
        self.last_status = ""
        self.dialog_open = False
        self.setting_switch_update = False
        self.key_controller = None
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
        .settings-button { min-width: 42px; padding: 6px 10px; }
        .task-row { padding: 10px 12px; border-radius: 8px; }
        .task-row-active { background: rgba(255,255,255,.12); }
        .task-title { font-size: 17px; }
        .task-title-completed { text-decoration-line: line-through; opacity: .55; }
        .status { opacity: .65; font-size: 12px; }
        .setup-title { font-size: 24px; font-weight: 700; }
        .setup-copy { opacity: .75; }
        .setup-button { padding: 12px; }
        .settings-section { font-weight: 700; margin-top: 10px; }
        .settings-row { padding: 2px 0; }
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

        self.list_label = Gtk.Label(label="")
        self.list_label.add_css_class("list-title")
        self.list_label.set_xalign(0)
        self.list_label.set_hexpand(True)
        top.append(self.list_label)

        self.sync_label = Gtk.Label(label="")
        self.sync_label.add_css_class("status")
        self.sync_label.set_xalign(1)
        top.append(self.sync_label)

        clear_btn = Gtk.Button(label="🧹")
        clear_btn.add_css_class("settings-button")
        clear_btn.set_tooltip_text("Clear completed tasks")
        clear_btn.connect("clicked", lambda *_: self.clear_completed_current_list())
        top.append(clear_btn)

        settings_btn = Gtk.Button(label="⚙")
        settings_btn.add_css_class("settings-button")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", self.show_settings_dialog)
        top.append(settings_btn)

        root.append(top)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(self.default_placeholder)
        self.entry.add_css_class("search-entry")
        self.entry.connect("changed", self.on_filter_changed)
        # Plain Enter should not add tasks. Ctrl+Enter is handled by the key controller.
        root.append(self.entry)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        # Keep keyboard focus in the filter entry. We manage the highlighted
        # row ourselves instead of letting Gtk.ListBox move focus to rows.
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_focusable(False)
        self.scroller.set_child(self.listbox)
        root.append(self.scroller)

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
        self.key_controller = controller
        self.add_controller(controller)

    def pause_main_controls(self) -> None:
        self.dialog_open = True

    def resume_main_controls(self, refocus: bool = True) -> None:
        self.dialog_open = False
        if refocus:
            self.focus_entry()

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
            if self.google_tasks_enabled() and self.google_ready():
                self.sync_in_background(interactive=False)

    def on_choose_local(self, button: Gtk.Button) -> None:
        self.enable_local_mode()

    def on_choose_google(self, button: Gtk.Button) -> None:
        self.enable_google_mode(interactive=True)

    def local_lists_enabled(self) -> bool:
        return bool(self.config.get("local_lists_enabled", True))

    def google_tasks_enabled(self) -> bool:
        return bool(self.config.get("google_tasks_enabled", self.config.get("sync_mode") == "google"))

    def google_ready(self) -> bool:
        token = xdg_config_dir() / "google_token.json"
        return self.google_tasks_enabled() and self.google_sync.has_client_secret() and token.exists()

    def is_google_list(self, task_list: TaskList | None) -> bool:
        return bool(task_list and (task_list.google_list_id or task_list.source == "google"))

    def ensure_at_least_one_source_enabled(self) -> None:
        if not self.local_lists_enabled() and not self.google_tasks_enabled():
            self.config.set("local_lists_enabled", True)

    def enable_local_mode(self) -> None:
        self.config.set("mode", "local_first")
        self.config.set("local_lists_enabled", True)
        self.stack.set_visible_child_name("tasks")
        self.load_last_list()
        self.refresh_tasks()
        self.set_status(f"{APP_VERSION} · Local lists enabled")
        self.ensure_first_run_shortcut()
        self.focus_entry()

    def enable_google_mode(self, interactive: bool = True) -> None:
        self.config.set("mode", "local_first")
        self.config.set("google_tasks_enabled", True)
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

    def hidden_google_list_ids(self) -> set[str]:
        raw = self.config.get("hidden_google_list_ids", [])
        if isinstance(raw, list):
            return {str(item) for item in raw if item}
        return set()

    def hide_google_list_id(self, google_list_id: str | None) -> None:
        if not google_list_id:
            return
        hidden = self.hidden_google_list_ids()
        hidden.add(google_list_id)
        self.config.set("hidden_google_list_ids", sorted(hidden))

    def unhide_google_list_id(self, google_list_id: str | None) -> None:
        if not google_list_id:
            return
        hidden = self.hidden_google_list_ids()
        if google_list_id in hidden:
            hidden.remove(google_list_id)
            self.config.set("hidden_google_list_ids", sorted(hidden))

    def get_google_status_text(self) -> str:
        if not self.google_tasks_enabled():
            return "Disabled"
        if not self.google_sync.has_client_secret():
            return "Not Connected"
        if not (xdg_config_dir() / "google_token.json").exists():
            return "Not Connected"
        if self.last_status:
            return self.last_status
        return "Connected"

    def show_settings_dialog(self, button: Gtk.Button | None = None) -> None:
        self.pause_main_controls()
        dialog = Gtk.Dialog(title="TaskPop Settings", transient_for=self, modal=True)
        dialog.set_default_size(560, 620)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title = Gtk.Label(label="TaskPop Settings")
        title.add_css_class("setup-title")
        title.set_xalign(0)
        title.set_hexpand(True)
        header.append(title)
        version = Gtk.Label(label=APP_VERSION.replace("-test", " test"))
        version.add_css_class("status")
        version.set_xalign(1)
        header.append(version)
        content.append(header)

        local_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        local_row.add_css_class("settings-row")
        local_label = Gtk.Label(label="Local Task Lists")
        local_label.set_xalign(0)
        local_label.set_hexpand(True)
        local_row.append(local_label)
        local_switch = Gtk.Switch()
        local_switch.set_active(self.local_lists_enabled())
        local_switch.connect("notify::active", lambda sw, _pspec: self.on_local_toggle(sw, sw.get_active()))
        local_row.append(local_switch)
        content.append(local_row)

        google_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        google_row.add_css_class("settings-row")
        google_label = Gtk.Label(label="Google Tasks")
        google_label.set_xalign(0)
        google_label.set_hexpand(True)
        google_row.append(google_label)
        google_switch = Gtk.Switch()
        google_switch.set_active(self.google_tasks_enabled())
        google_switch.connect("notify::active", lambda sw, _pspec: self.on_google_toggle(sw, sw.get_active()))
        google_row.append(google_switch)
        content.append(google_row)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_label = Gtk.Label(label=f"Status: {self.get_google_status_text()}")
        status_label.set_xalign(0)
        status_label.set_hexpand(True)
        status_row.append(status_label)
        sync_btn = Gtk.Button(label="Sync Now")
        sync_btn.set_sensitive(self.google_tasks_enabled() and self.google_sync.has_client_secret())
        sync_btn.connect("clicked", lambda *_: self._settings_sync_now(dialog))
        status_row.append(sync_btn)
        content.append(status_row)

        shortcut_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        shortcut_label = Gtk.Label(label=f"Global Shortcut: {self.config.get('shortcut_binding', '<Super>t')}")
        shortcut_label.set_xalign(0)
        shortcut_label.set_hexpand(True)
        shortcut_row.append(shortcut_label)
        shortcut_btn = Gtk.Button(label="Change")
        shortcut_btn.connect("clicked", lambda *_: self._settings_shortcut(dialog))
        shortcut_row.append(shortcut_btn)
        content.append(shortcut_row)

        create_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        create_label = Gtk.Label(label="Create New List")
        create_label.set_xalign(0)
        create_label.set_hexpand(True)
        create_row.append(create_label)

        local_list_btn = Gtk.Button(label="💻 Local")
        local_list_btn.set_sensitive(self.local_lists_enabled())
        local_list_btn.connect("clicked", lambda *_: self._settings_new_local_list(dialog))
        create_row.append(local_list_btn)

        google_list_btn = Gtk.Button(label="🌐 Google Tasks")
        google_list_btn.set_sensitive(self.google_tasks_enabled() and self.google_sync.has_client_secret())
        google_list_btn.connect("clicked", lambda *_: self._settings_new_google_list(dialog))
        create_row.append(google_list_btn)
        content.append(create_row)

        open_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        open_label = Gtk.Label(label="Open")
        open_label.set_xalign(0)
        open_label.set_hexpand(True)
        open_row.append(open_label)

        config_btn = Gtk.Button(label="Config Folder")
        config_btn.connect("clicked", lambda *_: self.open_config_folder())
        open_row.append(config_btn)

        oauth_btn = Gtk.Button(label="Google OAuth Guide")
        oauth_btn.connect("clicked", lambda *_: self.open_google_setup_guide())
        open_row.append(oauth_btn)
        content.append(open_row)

        help_title = Gtk.Label(label="TaskPop Navigation/Shortcuts")
        help_title.add_css_class("settings-section")
        help_title.set_xalign(0)
        content.append(help_title)

        help_text = Gtk.Label(
            label=(
                "• To filter and find tasks: type in the main input\n"
                "• To add a task in the current list: type the task name and press Ctrl+Enter\n"
                "• To edit the selected task: Shift+Enter or Ctrl+E\n"
                "• To rename the current list: Ctrl+L\n"
                "• To copy the selected task text: Ctrl+C\n"
                "• To open Settings: Ctrl+S or :settings\n"
                "• To clear completed tasks: Ctrl+K, 🧹, or :clear\n"
                "• To switch lists: Ctrl+Tab / Ctrl+Shift+Tab\n"
                "• To jump to a list: Ctrl+1 to Ctrl+9, Ctrl+0 for the last visible list\n"
                "• To show commands, type ':'\n"
                "• Example: ':list' or ':google' filters matching commands and descriptions\n"
                "• Use Up and Down to navigate tasks and commands\n"
                "• Press Space to tick/untick a selected task\n"
                "• Press Ctrl+Enter to trigger a selected command"
            )
        )
        help_text.set_xalign(0)
        help_text.set_wrap(True)
        content.append(help_text)

        def on_response(d: Gtk.Dialog, response: int) -> None:
            d.destroy()
            self.resume_main_controls(refocus=True)

        dialog.connect("response", on_response)
        dialog.present()

    def set_switch_safely(self, switch: Gtk.Switch | None, active: bool) -> None:
        if not switch:
            return
        self.setting_switch_update = True
        try:
            switch.set_active(active)
        finally:
            self.setting_switch_update = False

    def apply_source_state(self, local_enabled: bool, google_enabled: bool, status: str = "") -> None:
        if not local_enabled and not google_enabled:
            local_enabled = True

        self.config.set("local_lists_enabled", bool(local_enabled))
        self.config.set("google_tasks_enabled", bool(google_enabled))
        self.config.set("sync_mode", "google" if google_enabled else "none")

        self.refresh_after_source_toggle()
        if status:
            self.set_status(status)

    def on_local_toggle(self, switch: Gtk.Switch, active: bool) -> None:
        if self.setting_switch_update:
            return

        if not active and not self.google_tasks_enabled():
            self.set_switch_safely(switch, True)
            self.show_source_dependency_dialog(
                "You need to enable Google Tasks before disabling Local Lists.",
                lambda: self.apply_source_state(
                    local_enabled=False,
                    google_enabled=True,
                    status="Google Tasks enabled · Local lists disabled",
                ),
            )
            return

        self.config.set("local_lists_enabled", bool(active))
        self.refresh_after_source_toggle()
        self.set_status("Local lists enabled" if active else "Local lists disabled")

    def on_google_toggle(self, switch: Gtk.Switch, active: bool) -> None:
        if self.setting_switch_update:
            return

        if not active and not self.local_lists_enabled():
            self.set_switch_safely(switch, True)
            self.show_source_dependency_dialog(
                "You need to enable Local Lists before disabling Google Tasks.",
                lambda: self.apply_source_state(
                    local_enabled=True,
                    google_enabled=False,
                    status="Local lists enabled · Google Tasks disabled",
                ),
            )
            return

        self.config.set("google_tasks_enabled", bool(active))
        self.config.set("sync_mode", "google" if active else "none")

        if active and not self.google_sync.has_client_secret():
            self.set_status("Google setup needed · config folder opened")
            self.open_google_setup_location()
        elif active and self.google_sync.has_client_secret():
            self.set_status("Google Tasks enabled")
        else:
            self.set_status("Google Tasks disabled")

        self.refresh_after_source_toggle()

    def refresh_after_source_toggle(self) -> None:
        self.refresh_lists()
        if not self.current_list or not any(l.id == self.current_list.id for l in self.lists):
            self.current_list = self.lists[0] if self.lists else self.db.get_last_list()
        self.update_list_label()
        self.refresh_tasks()

    def _settings_local(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.resume_main_controls(refocus=False)
        self.enable_local_mode()

    def _settings_google(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.resume_main_controls(refocus=False)
        GLib.idle_add(lambda: (self.start_google_setup_flow(), False)[1])

    def _settings_sync_now(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.resume_main_controls(refocus=False)
        GLib.idle_add(lambda: (self.start_sync_now_flow(), False)[1])

    def _settings_new_local_list(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.resume_main_controls(refocus=False)
        GLib.idle_add(lambda: (self.start_new_list_flow("local"), False)[1])

    def _settings_new_google_list(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.resume_main_controls(refocus=False)
        GLib.idle_add(lambda: (self.start_new_list_flow("google"), False)[1])

    def _settings_new_list(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.resume_main_controls(refocus=False)
        GLib.idle_add(lambda: (self.start_new_list_flow("local"), False)[1])

    def _settings_shortcut(self, dialog: Gtk.Dialog) -> None:
        dialog.destroy()
        self.resume_main_controls(refocus=False)
        GLib.idle_add(lambda: (self.start_shortcut_flow(), False)[1])

    def start_new_list_flow(self, source: str = "local") -> None:
        if source == "google" and not self.google_ready():
            self.show_google_not_ready_dialog()
            return
        self.pending_action = "new_list_google" if source == "google" else "new_list_local"
        self.entry.set_text("")
        label = "Google Tasks list" if source == "google" else "local list"
        self.entry.set_placeholder_text(f"New {label} name · Ctrl+Enter to create")
        self.set_status(f"Type new {label} name, then press Ctrl+Enter")
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

        if not self.google_ready():
            self.show_google_not_ready_dialog()
            return

        self.set_status("Syncing…")
        self.connect_google_in_background(interactive=True)

    def clear_pending_action(self) -> None:
        self.pending_action = None
        self.pending_task_id = None
        self.current_filter = ""
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

    def show_primary_google_list_warning(self) -> None:
        self.pause_main_controls()
        dialog = Gtk.Dialog(title="Google Tasks Primary List", transient_for=self, modal=True)
        dialog.set_default_size(460, 180)
        dialog.add_button("OK", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        label = Gtk.Label(
            label="This is your primary list in Google Tasks. This cannot be deleted or converted to a Local list"
        )
        label.set_wrap(True)
        label.set_xalign(0)
        content.append(label)

        def on_response(d: Gtk.Dialog, response: int) -> None:
            d.destroy()
            self.resume_main_controls(refocus=True)

        dialog.connect("response", on_response)
        dialog.present()

    def show_source_dependency_dialog(self, message: str, proceed_cb) -> None:
        self.pause_main_controls()
        dialog = Gtk.Dialog(title="TaskPop Lists", transient_for=self, modal=True)
        dialog.set_default_size(460, 180)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Yes, Proceed", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        label = Gtk.Label(label=message)
        label.set_wrap(True)
        label.set_xalign(0)
        content.append(label)

        def on_response(d: Gtk.Dialog, response: int) -> None:
            d.destroy()
            self.resume_main_controls(refocus=True)
            if response == Gtk.ResponseType.OK:
                proceed_cb()

        dialog.connect("response", on_response)
        dialog.present()

    def show_google_not_ready_dialog(self) -> None:
        self.pause_main_controls()
        dialog = Gtk.Dialog(title="Google Tasks Not Enabled", transient_for=self, modal=True)
        dialog.set_default_size(460, 220)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        label = Gtk.Label(
            label=(
                "Google Tasks is not enabled or connected.\\n\\n"
                "Enable 'Google Tasks' from Settings and setup the Google OAuth for this to work.\\n\\n"
                "See 'Google OAuth Setup Guide' in Settings."
            )
        )
        label.set_wrap(True)
        label.set_xalign(0)
        content.append(label)

        settings_btn = Gtk.Button(label="Open Settings")
        settings_btn.connect("clicked", lambda *_: (dialog.response(Gtk.ResponseType.CLOSE), self.show_settings_dialog()))
        content.append(settings_btn)

        def on_response(d: Gtk.Dialog, response: int) -> None:
            d.destroy()
            self.resume_main_controls(refocus=True)

        dialog.connect("response", on_response)
        dialog.present()

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
        all_lists = self.db.list_lists()
        self.ensure_at_least_one_source_enabled()
        include_local = self.local_lists_enabled()
        include_google = self.google_tasks_enabled()

        self.lists = [
            task_list for task_list in all_lists
            if (self.is_google_list(task_list) and include_google)
            or ((not self.is_google_list(task_list)) and include_local)
        ]

        # Never leave the app without a visible list.
        if not self.lists and all_lists:
            self.lists = [all_lists[0]]

    def load_last_list(self) -> None:
        self.refresh_lists()
        self.current_list = self.db.get_last_list()
        self.update_list_label()

    def update_list_label(self) -> None:
        if not self.current_list:
            self.list_label.set_text("0/0 💻 No list")
            return
        index = next((i for i, l in enumerate(self.lists) if l.id == self.current_list.id), 0) + 1
        icon = "🌐" if (self.current_list.google_list_id or self.current_list.source == "google") else "💻"
        total = max(len(self.lists), 1)
        self.list_label.set_text(f"{index}/{total} {icon} {self.current_list.title}")

    def get_selected_task(self) -> Task | None:
        if not self.task_rows or self.selected_index >= len(self.task_rows):
            return None
        task, _row = self.task_rows[self.selected_index]
        return task

    def start_edit_selected_task(self) -> None:
        task = self.get_selected_task()
        if not task:
            self.set_status("No task selected")
            return
        self.pending_action = "edit_task"
        self.pending_task_id = task.id
        self.current_filter = ""
        self.entry.set_placeholder_text("Edit task · Ctrl+Enter to save · Esc cancel")
        self.entry.set_text(task.title)
        self.entry.select_region(0, len(task.title))
        self.set_status("Editing task · Ctrl+Enter to save")
        self.focus_entry()

    def start_rename_current_list(self) -> None:
        if not self.current_list:
            self.set_status("No list selected")
            return
        self.pending_action = "rename_list"
        self.pending_task_id = None
        self.current_filter = ""
        self.entry.set_placeholder_text("Rename list · Ctrl+Enter to save · Esc cancel")
        self.entry.set_text(self.current_list.title)
        self.entry.select_region(0, len(self.current_list.title))
        self.set_status("Renaming list · Ctrl+Enter to save")
        self.focus_entry()

    def copy_selected_task_to_clipboard(self) -> None:
        task = self.get_selected_task()
        if not task:
            self.set_status("No task selected")
            return
        try:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set_content(Gdk.ContentProvider.new_for_value(task.title))
            self.set_status("Task copied")
        except Exception as exc:
            try:
                subprocess.run(["wl-copy"], input=task.title, text=True, check=True)
                self.set_status("Task copied")
            except Exception:
                self.set_status("Could not copy task")
                print(f"TaskPop copy failed: {exc}", file=sys.stderr)

    def on_filter_changed(self, entry: Gtk.Entry) -> None:
        # Do not grab focus or change cursor position here.
        # In GTK this can select the whole entry after every refresh,
        # causing the next typed character to replace the previous text.
        if self.pending_action in ("edit_task", "rename_list"):
            return
        self.current_filter = entry.get_text()
        self.refresh_tasks(keep_selection=True)

    def add_from_entry(self) -> None:
        text = self.entry.get_text().strip()

        exact_commands = {
            ":unlist", ":list-c-gt", ":convert-to-google-task", ":list-c-l", ":convert-to-local",
            ":sync", ":clear", ":settings", ":order-az", ":order-za", ":order-lg", ":order-gl",
            ":enable-gt", ":disable-gt", ":enable-l", ":disable-l"
        }
        if (
            text.startswith(":")
            and self.command_matches
            and text not in exact_commands
            and not text.startswith(":list-l ")
            and not text.startswith(":list-gt ")
            and not text.startswith(":rename ")
            and not text.startswith(":reorder ")
            and not text.startswith(":shortcut ")
        ):
            self.run_selected_command()
            return

        if self.pending_action == "edit_task":
            if not text or not self.pending_task_id:
                return
            task = self.db.get_task(self.pending_task_id)
            if not task:
                self.clear_pending_action()
                self.set_status("Selected task no longer exists")
                return
            task_list = self.db.get_list(task.list_id)
            dirty = self.is_google_list(task_list)
            self.db.update_task_title(task.id, text, dirty=dirty)
            self.clear_pending_action()
            self.refresh_tasks()
            self.set_status("Task updated")
            if dirty and self.google_ready():
                self.connect_google_in_background(interactive=False)
            return

        if self.pending_action == "rename_list":
            if not text:
                return
            self.rename_current_list(text)
            self.clear_pending_action()
            return

        if self.pending_action in ("new_list_local", "new_list_google"):
            if not text:
                return
            source = "google" if self.pending_action == "new_list_google" else "local"
            self.create_list_from_name(text, source=source)
            self.clear_pending_action()
            return

        if self.pending_action == "shortcut":
            if not text:
                return
            ok, message = self.configure_global_shortcut(text)
            self.clear_pending_action()
            self.set_status(message)
            return

        if text.startswith(":list-l "):
            name = text[len(":list-l "):].strip()
            if name:
                self.create_list_from_name(name, source="local")
            return

        if text.startswith(":list-gt "):
            name = text[len(":list-gt "):].strip()
            if name:
                self.create_list_from_name(name, source="google")
            return

        if text.startswith(":rename "):
            new_name = text[len(":rename "):].strip()
            if new_name:
                self.rename_current_list(new_name)
            return

        if text.startswith(":reorder "):
            raw = text[len(":reorder "):].strip()
            try:
                position = int(raw)
            except ValueError:
                self.set_status("Position not in range.")
                return
            self.reorder_current_list(position)
            return

        if text.startswith(":shortcut "):
            binding = text[len(":shortcut "):].strip()
            if binding:
                ok, message = self.configure_global_shortcut(binding)
                self.entry.set_text("")
                self.set_status(message)
            return

        if text == ":unlist":
            self.confirm_remove_current_list()
            return

        if text in (":list-c-gt", ":convert-to-google-task"):
            self.convert_current_list_to_google()
            return

        if text in (":list-c-l", ":convert-to-local"):
            self.convert_current_list_to_local()
            return

        if text == ":order-az":
            self.order_visible_lists("az")
            return

        if text == ":order-za":
            self.order_visible_lists("za")
            return

        if text == ":order-lg":
            self.order_visible_lists("lg")
            return

        if text == ":order-gl":
            self.order_visible_lists("gl")
            return

        if text == ":clear":
            self.clear_completed_current_list()
            return

        if text == ":settings":
            self.entry.set_text("")
            self.show_settings_dialog()
            return

        if text == ":enable-gt":
            self.config.set("google_tasks_enabled", True)
            self.config.set("sync_mode", "google")
            self.entry.set_text("")
            self.refresh_after_source_toggle()
            self.set_status("Google Tasks enabled")
            return

        if text == ":disable-gt":
            if not self.local_lists_enabled():
                self.show_source_dependency_dialog(
                    "You need to enable Local Lists before disabling Google Tasks.",
                    lambda: self.apply_source_state(
                        local_enabled=True,
                        google_enabled=False,
                        status="Local lists enabled · Google Tasks disabled",
                    ),
                )
                return
            self.config.set("google_tasks_enabled", False)
            self.config.set("sync_mode", "none")
            self.entry.set_text("")
            self.refresh_after_source_toggle()
            self.set_status("Google Tasks disabled")
            return

        if text == ":enable-l":
            self.config.set("local_lists_enabled", True)
            self.entry.set_text("")
            self.refresh_after_source_toggle()
            self.set_status("Local lists enabled")
            return

        if text == ":disable-l":
            if not self.google_tasks_enabled():
                self.show_source_dependency_dialog(
                    "You need to enable Google Tasks before disabling Local Lists.",
                    lambda: self.apply_source_state(
                        local_enabled=False,
                        google_enabled=True,
                        status="Google Tasks enabled · Local lists disabled",
                    ),
                )
                return
            self.config.set("local_lists_enabled", False)
            self.entry.set_text("")
            self.refresh_after_source_toggle()
            self.set_status("Local lists disabled")
            return

        if text == ":sync":
            self.start_sync_now_flow()
            return

        if text.startswith(":"):
            self.set_status("Unknown command. Type : to see commands.")
            return

        if not text or not self.current_list:
            return

        is_google = self.is_google_list(self.current_list)
        self.db.add_task(self.current_list.id, text, dirty=is_google)
        self.entry.set_text("")
        self.refresh_tasks()
        if is_google and self.google_ready():
            self.connect_google_in_background(interactive=False)

    def create_list_from_name(self, name: str, source: str = "local") -> None:
        name = name.strip()
        if not name:
            return

        if source == "google":
            if not self.google_ready():
                self.show_google_not_ready_dialog()
                return
            try:
                google_list_id = self.google_sync.create_remote_task_list(name, interactive=True)
                self.unhide_google_list_id(google_list_id)
            except Exception as exc:
                self.set_status("Could not create Google Tasks list")
                print(f"TaskPop create Google list failed: {exc}", file=sys.stderr)
                return
            list_id = self.db.create_list(name, source="google", google_list_id=google_list_id, last_used=True)
        else:
            if not self.local_lists_enabled():
                self.config.set("local_lists_enabled", True)
            list_id = self.db.create_list(name, source="local", last_used=True)

        self.current_list = self.db.get_list(list_id)
        self.refresh_lists()
        self.update_list_label()
        self.entry.set_text("")
        self.refresh_tasks()
        icon = "🌐" if source == "google" else "💻"
        self.set_status(f"{icon} List created: {name}")

    def rename_current_list(self, new_name: str) -> None:
        if not self.current_list:
            return
        new_name = new_name.strip()
        if not new_name:
            return

        old_name = self.current_list.title
        if self.is_google_list(self.current_list) and self.current_list.google_list_id:
            if not self.google_ready():
                self.show_google_not_ready_dialog()
                return
            try:
                self.google_sync.rename_remote_task_list(self.current_list.google_list_id, new_name, interactive=True)
            except Exception as exc:
                self.set_status("Could not rename Google Tasks list")
                print(f"TaskPop rename Google list failed: {exc}", file=sys.stderr)
                return

        self.db.rename_list(self.current_list.id, new_name)
        self.current_list = self.db.get_list(self.current_list.id)
        self.entry.set_text("")
        self.refresh_lists()
        self.update_list_label()
        self.refresh_tasks()
        self.set_status(f"Renamed: {old_name} → {new_name}")

    def clear_completed_current_list(self) -> None:
        if not self.current_list:
            return

        completed = self.db.completed_tasks(self.current_list.id)
        if not completed:
            self.entry.set_text("")
            self.set_status("No completed tasks to clear")
            return

        if self.is_google_list(self.current_list) and self.current_list.google_list_id:
            if not self.google_ready():
                self.show_google_not_ready_dialog()
                return
            try:
                for task in completed:
                    if task.google_task_id:
                        self.google_sync.delete_remote_task(
                            self.current_list.google_list_id,
                            task.google_task_id,
                            interactive=True,
                        )
            except Exception as exc:
                self.set_status("Could not clear Google completed tasks")
                print(f"TaskPop clear Google completed failed: {exc}", file=sys.stderr)
                return

        count = self.db.clear_completed(self.current_list.id)
        self.entry.set_text("")
        self.refresh_tasks()
        self.set_status(f"Cleared {count} completed task{'s' if count != 1 else ''}")

    def confirm_remove_current_list(self) -> None:
        if not self.current_list:
            return

        self.refresh_lists()
        if len(self.db.list_lists()) <= 1:
            self.entry.set_text("")
            self.set_status("Cannot remove the only list")
            return

        self.pause_main_controls()
        list_title = self.current_list.title

        dialog = Gtk.Dialog(title="Delete List", transient_for=self, modal=True)
        dialog.set_default_size(420, 180)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("OK", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        label = Gtk.Label(
            label=f"Delete '{list_title}' and all tasks under it?\\n\\nType DELETE to confirm."
        )
        label.set_xalign(0)
        label.set_wrap(True)
        content.append(label)

        confirm_entry = Gtk.Entry()
        confirm_entry.set_placeholder_text("DELETE")
        confirm_entry.connect("activate", lambda e: dialog.response(Gtk.ResponseType.OK))
        content.append(confirm_entry)

        def on_response(d: Gtk.Dialog, response: int) -> None:
            typed = confirm_entry.get_text().strip()
            d.destroy()
            self.resume_main_controls(refocus=False)
            if response == Gtk.ResponseType.OK and typed == "DELETE":
                self.remove_current_list_confirmed()
            else:
                self.set_status("Delete cancelled")
                self.focus_entry()

        dialog.connect("response", on_response)
        dialog.present()
        GLib.idle_add(lambda: (confirm_entry.grab_focus(), False)[1])

    def remove_current_list(self) -> None:
        self.confirm_remove_current_list()

    def remove_current_list_confirmed(self) -> None:
        if not self.current_list:
            return

        removed_title = self.current_list.title
        removed_id = self.current_list.id
        is_google = self.is_google_list(self.current_list)
        google_list_id = self.current_list.google_list_id

        if is_google and google_list_id:
            if not self.google_ready():
                self.show_google_not_ready_dialog()
                return
            try:
                self.google_sync.delete_remote_task_list(google_list_id, interactive=True)
            except Exception as exc:
                print(f"TaskPop Google list delete refused: {exc}", file=sys.stderr)
                self.show_primary_google_list_warning()
                return

        self.db.delete_list(removed_id)
        self.refresh_lists()

        self.current_list = self.lists[0] if self.lists else self.db.get_last_list()
        if self.current_list:
            self.db.set_last_list(self.current_list.id)

        self.entry.set_text("")
        self.completed_visible.clear()
        self.update_list_label()
        self.refresh_tasks()
        self.set_status(f"Removed list: {removed_title}")

    def convert_current_list_to_google(self) -> None:
        if not self.current_list:
            return
        if self.is_google_list(self.current_list):
            self.entry.set_text("")
            self.set_status("Current list is already a Google Tasks list")
            return
        if not self.google_ready():
            self.show_google_not_ready_dialog()
            return

        title = self.current_list.title
        try:
            google_list_id = self.google_sync.create_remote_task_list(title, interactive=True)
            self.db.convert_list_to_google(self.current_list.id, google_list_id)
            self.current_list = self.db.get_list(self.current_list.id)
            self.entry.set_text("")
            self.refresh_lists()
            self.update_list_label()
            self.refresh_tasks()
            self.set_status(f"Converted to Google Tasks: {title}")
            self.connect_google_in_background(interactive=False)
        except Exception as exc:
            self.set_status("Could not convert list to Google Tasks")
            print(f"TaskPop convert to Google failed: {exc}", file=sys.stderr)

    def convert_current_list_to_local(self) -> None:
        if not self.current_list:
            return
        if not self.is_google_list(self.current_list):
            self.entry.set_text("")
            self.set_status("Current list is already local")
            return

        title = self.current_list.title
        google_list_id = self.current_list.google_list_id

        if google_list_id:
            if not self.google_ready():
                self.show_google_not_ready_dialog()
                return
            try:
                self.google_sync.delete_remote_task_list(google_list_id, interactive=True)
            except Exception as exc:
                print(f"TaskPop Google list delete refused during convert: {exc}", file=sys.stderr)
                self.show_primary_google_list_warning()
                return

        self.db.convert_list_to_local(self.current_list.id)
        self.current_list = self.db.get_list(self.current_list.id)
        self.entry.set_text("")
        self.refresh_lists()
        self.update_list_label()
        self.refresh_tasks()
        self.set_status(f"Converted to local: {title}")

    def reorder_current_list(self, position: int) -> None:
        self.refresh_lists()
        if not self.current_list or not self.lists:
            return

        total = len(self.lists)
        if position < 1 or position > total:
            self.set_status("Position not in range.")
            return

        ordered_ids = [lst.id for lst in self.lists]
        current_id = self.current_list.id
        if current_id not in ordered_ids:
            return

        ordered_ids.remove(current_id)
        ordered_ids.insert(position - 1, current_id)

        self.db.set_list_order(ordered_ids)
        self.refresh_lists()
        self.current_list = self.db.get_list(current_id)
        self.update_list_label()
        self.refresh_tasks()
        self.entry.set_text("")
        self.set_status(f"Moved list to {position}/{total}")

    def order_visible_lists(self, mode: str) -> None:
        self.refresh_lists()
        if not self.lists:
            return

        if mode == "az":
            ordered = sorted(self.lists, key=lambda l: l.title.lower())
            label = "Ordered A to Z"
        elif mode == "za":
            ordered = sorted(self.lists, key=lambda l: l.title.lower(), reverse=True)
            label = "Ordered Z to A"
        elif mode == "lg":
            ordered = sorted(self.lists, key=lambda l: (self.is_google_list(l), l.title.lower()))
            label = "Local lists first"
        elif mode == "gl":
            ordered = sorted(self.lists, key=lambda l: (not self.is_google_list(l), l.title.lower()))
            label = "Google Tasks lists first"
        else:
            return

        current_id = self.current_list.id if self.current_list else None
        self.db.set_list_order([lst.id for lst in ordered])
        self.refresh_lists()
        if current_id:
            self.current_list = self.db.get_list(current_id)
        self.update_list_label()
        self.refresh_tasks()
        self.entry.set_text("")
        self.set_status(label)

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
        self.command_matches = []
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
        old_index = self.selected_index
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)

        self.task_rows = []
        raw = query.strip().lower()
        q = raw[1:] if raw.startswith(":") else raw
        words = [part for part in q.split() if part]

        self.command_matches = []
        for command, description in COMMANDS:
            haystack = f"{command.lower()} {command.lower().lstrip(':')} {description.lower()}"
            if raw in (":", "") or not words or all(word in haystack for word in words):
                self.command_matches.append((command, description))

        if not self.command_matches:
            self.command_matches = [("No matching command", "Commands start with : and cannot be added as tasks")]

        for command, description in self.command_matches:
            row = self.make_command_row(command, description)
            self.listbox.append(row)
            self.task_rows.append((None, row))

        self.selected_index = min(old_index, len(self.task_rows) - 1) if self.task_rows else 0
        self.apply_selection_style()
        self.set_status("Command mode · ↑/↓ choose · Ctrl+Enter run/fill")

    def run_selected_command(self) -> None:
        if not self.command_matches or self.selected_index >= len(self.command_matches):
            return
        command, _description = self.command_matches[self.selected_index]
        if command == "No matching command":
            self.set_status("Unknown command. Type : to see commands.")
            return

        # Commands with placeholders need more text, so fill the input.
        if "<" in command and ">" in command and "<binding>" not in command:
            prefix = command.split("<", 1)[0]
            self.entry.set_text(prefix)
            self.entry.set_position(-1)
            self.set_status("Type the value, then Ctrl+Enter")
            return
        if "<binding>" in command:
            prefix = command.split("<", 1)[0]
            self.entry.set_text(prefix)
            self.entry.set_position(-1)
            self.set_status("Type shortcut, then Ctrl+Enter")
            return

        self.entry.set_text(command)
        self.entry.set_position(-1)
        self.add_from_entry()

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
        if self.dialog_open:
            return False
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

        if shift and keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.start_edit_selected_task()
            return True

        if ctrl and keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.add_from_entry()
            return True

        if ctrl and keyval in (Gdk.KEY_e, Gdk.KEY_E):
            self.start_edit_selected_task()
            return True

        if ctrl and keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self.start_rename_current_list()
            return True

        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy_selected_task_to_clipboard()
            return True

        if ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.show_settings_dialog()
            return True

        if ctrl and keyval in (Gdk.KEY_k, Gdk.KEY_K):
            self.clear_completed_current_list()
            return True

        if ctrl and keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self.switch_to_list_position(0)
            return True

        if ctrl and keyval in (
            Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3, Gdk.KEY_4, Gdk.KEY_5,
            Gdk.KEY_6, Gdk.KEY_7, Gdk.KEY_8, Gdk.KEY_9,
            Gdk.KEY_KP_1, Gdk.KEY_KP_2, Gdk.KEY_KP_3, Gdk.KEY_KP_4, Gdk.KEY_KP_5,
            Gdk.KEY_KP_6, Gdk.KEY_KP_7, Gdk.KEY_KP_8, Gdk.KEY_KP_9,
        ):
            digit_map = {
                Gdk.KEY_1: 1, Gdk.KEY_KP_1: 1,
                Gdk.KEY_2: 2, Gdk.KEY_KP_2: 2,
                Gdk.KEY_3: 3, Gdk.KEY_KP_3: 3,
                Gdk.KEY_4: 4, Gdk.KEY_KP_4: 4,
                Gdk.KEY_5: 5, Gdk.KEY_KP_5: 5,
                Gdk.KEY_6: 6, Gdk.KEY_KP_6: 6,
                Gdk.KEY_7: 7, Gdk.KEY_KP_7: 7,
                Gdk.KEY_8: 8, Gdk.KEY_KP_8: 8,
                Gdk.KEY_9: 9, Gdk.KEY_KP_9: 9,
            }
            self.switch_to_list_position(digit_map.get(keyval, 0))
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
        GLib.idle_add(self.ensure_selected_row_visible)

    def ensure_selected_row_visible(self) -> bool:
        if not self.task_rows or self.selected_index >= len(self.task_rows):
            return False
        try:
            row = self.task_rows[self.selected_index][1]
            alloc = row.get_allocation()
            adj = self.scroller.get_vadjustment()
            top = float(alloc.y)
            bottom = float(alloc.y + alloc.height)
            view_top = float(adj.get_value())
            view_bottom = view_top + float(adj.get_page_size())

            if top < view_top:
                adj.set_value(max(adj.get_lower(), top))
            elif bottom > view_bottom:
                adj.set_value(min(adj.get_upper() - adj.get_page_size(), bottom - adj.get_page_size()))
        except Exception:
            pass
        return False

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
        if task is None:
            return
        new_status = self.db.toggle_task(task.id)
        if new_status == "completed":
            self.completed_visible.add(task.id)
        else:
            self.completed_visible.discard(task.id)
        self.refresh_tasks(keep_selection=True)
        if self.google_ready() and self.is_google_list(self.current_list):
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

    def switch_to_list_position(self, position: int) -> None:
        self.refresh_lists()
        if not self.lists:
            return

        if position == 0:
            index = len(self.lists) - 1
        else:
            index = position - 1

        if index < 0 or index >= len(self.lists):
            return

        self.current_list = self.lists[index]
        self.db.set_last_list(self.current_list.id)
        self.completed_visible.clear()
        self.entry.set_text("")
        self.update_list_label()
        self.refresh_tasks()
        self.set_status(f"Opened list {index + 1}/{len(self.lists)}")

    def focus_entry(self) -> None:
        if self.dialog_open:
            return
        def _focus():
            if self.dialog_open:
                return False
            if hasattr(self.entry, "grab_focus_without_selecting"):
                self.entry.grab_focus_without_selecting()
            else:
                self.entry.grab_focus()
            self.entry.set_position(-1)
            return False
        GLib.idle_add(_focus)

    def refocus_entry_end(self) -> None:
        if self.dialog_open:
            return
        def _focus():
            if self.dialog_open:
                return False
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
        self.last_status = text
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
