# TaskPop

![TaskPop screenshot](assets/taskpop-screenshot.png)

TaskPop is a fast, keyboard-first Ubuntu/GNOME task popup with local SQLite task lists and optional Google Tasks sync.

See [Changelog.md](Changelog.md) for release history.

## Features

- Fast popup task list for Ubuntu/GNOME.
- Local-first task storage using SQLite.
- Optional Google Tasks integration through browser OAuth.
- Separate local lists and Google Tasks lists.
- Keyboard navigation for tasks, lists, and commands.
- In-place task details panel with notes, smart date/time input, and reminder fields.
- Command mode by typing `:`.
- Custom app icon and GNOME shortcut support.

## Install on Ubuntu

```bash
cd taskpop_mvp
./install_ubuntu.sh
./install_shortcut_gnome.sh
taskpop
```

The shortcut installer binds:

```text
Super + T → TaskPop
```

## Google Tasks setup

1. Create/select a project in Google Cloud Console.
2. Enable Google Tasks API.
3. Configure OAuth consent.
4. Add your Google account as a test user.
5. Create OAuth Client ID → Desktop app.
6. Download the JSON file.
7. Save it as:

```text
~/.config/taskpop/google_client_secret.json
```

Then open TaskPop → Settings → enable Google Tasks → Sync Now.

## How it works

TaskPop keeps local lists and Google Tasks lists separate.

- 💻 Local lists stay local.
- 🌐 Google Tasks lists sync with Google Tasks.
- Both can be enabled at the same time.
- You cannot disable both Local Lists and Google Tasks at the same time.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Super + T` | Open/close TaskPop |
| `Ctrl + Enter` | Add task / run selected command |
| `Ctrl + D` | Open task details panel |
| `Shift + Enter` | Open task details panel |
| `Ctrl + E` | Quick edit selected task name |
| `Ctrl + L` | Rename current list |
| `Ctrl + C` | Copy selected task text |
| `Ctrl + O` | Open Settings |
| `Ctrl + S` | Save in details/settings; sync in list view |
| `Ctrl + K` | Clear completed tasks |
| `Ctrl + Tab` | Next list |
| `Ctrl + Shift + Tab` | Previous list |
| `Ctrl + 1` … `Ctrl + 9` | Jump to visible list number |
| `Ctrl + 0` | Jump to last visible list |
| `↑` / `↓` | Navigate tasks or commands |
| `Space` | Tick/untick selected task when input is empty |
| `Esc` | Close popup or cancel current action |

## Commands

Type `:` to show commands. Continue typing to filter command names and descriptions.

| Command | Action |
|---|---|
| `:list-l <name>` | Create local list |
| `:list-gt <name>` | Create Google Tasks list |
| `:unlist` | Delete current list after typing `DELETE` |
| `:rename <New List Name>` | Rename current list |
| `:reorder <number>` | Move current list to a visible position |
| `:order-az` | Order visible lists A to Z |
| `:order-za` | Order visible lists Z to A |
| `:order-lg` | Order local lists first, then Google Tasks lists |
| `:order-gl` | Order Google Tasks lists first, then local lists |
| `:clear` | Clear completed tasks from current list |
| `:settings` | Open Settings |
| `:list-c-gt` | Convert local list to Google Tasks |
| `:convert-to-google-task` | Same as `:list-c-gt` |
| `:list-c-l` | Convert Google Tasks list to local |
| `:convert-to-local` | Same as `:list-c-l` |
| `:enable-gt` | Show/enable Google Tasks lists |
| `:disable-gt` | Hide/disable Google Tasks lists |
| `:enable-l` | Show/enable local lists |
| `:disable-l` | Hide/disable local lists |
| `:shortcut <binding>` | Change global shortcut |
| `:sync` | Sync Google Tasks if connected |

## Notes

The primary Google Tasks list cannot be deleted by Google. If you try to delete or convert it to local, TaskPop shows a warning and leaves it unchanged.

## Planned for future

- Desktop reminder notifications.
- Recurring tasks.
- More shortcut keys.
- Better recurring task support.
- Search across all lists.
- Import/export.
- Packaging as a `.deb`.


## Google Tasks date/time note

Google Tasks sync supports task title, notes, completion status, and due date. Google Tasks API stores only the due date and discards due time, so TaskPop keeps due time and reminder timing locally.
