# TaskPop

![TaskPop screenshot](assets/taskpop-screenshot.png)

A fast local-first Ubuntu task popup with optional Google Tasks sync.

## What it does

- Opens like a small launcher window.
- Works locally with SQLite even without Google.
- Optional Google Tasks sync.
- `Ctrl+Enter` adds a task from the filter box.
- `↑` / `↓` navigates tasks.
- `Space` completes/uncompletes the selected task when the filter box is empty.
- Completed tasks stay visible until the popup is closed.
- `Ctrl+Tab` switches task lists.
- Opens the last-used list.
- Settings cog lets you switch between local-only and Google sync.
- Settings cog lets you create additional local lists.
- `Esc` closes the popup.

## Install on Ubuntu

```bash
cd taskpop_mvp
./install_ubuntu.sh
```

Then run:

```bash
taskpop
```

Optional GNOME shortcut:

```bash
./install_shortcut_gnome.sh
```

This binds:

```text
Super + T → TaskPop
```

## First setup

On first launch, choose:

1. **Use locally only**  
   Tasks are stored only in local SQLite.

2. **Sync with Google Tasks**  
   TaskPop remains local-first, but syncs with Google Tasks when connected.

## Google Tasks setup

TaskPop cannot ship a Google OAuth client secret inside an open-source repo.
For your own local setup:

1. Create a Google Cloud project.
2. Enable the Google Tasks API.
3. Create an OAuth Client ID.
4. Choose **Desktop app**.
5. Download the client JSON.
6. Save it as:

```text
~/.config/taskpop/google_client_secret.json
```

Then open TaskPop and choose **Sync with Google Tasks**.
A browser login will open.

The token is stored locally at:

```text
~/.config/taskpop/google_token.json
```

## Data locations

```text
Database: ~/.local/share/taskpop/taskpop.db
Config:   ~/.config/taskpop/config.json
Google:   ~/.config/taskpop/google_client_secret.json
Token:    ~/.config/taskpop/google_token.json
```

## Current MVP limitations

- No task editing UI yet.
- No task notes UI yet.
- No due-date UI yet.
- Google sync is best-effort and designed as a starting point.
- Local tasks are uploaded to Google on first successful sync.

## Suggested next features

- `Ctrl+L` to create/switch lists.
- `Ctrl+E` to edit selected task.
- `Delete` to delete selected task.
- Due dates with natural language like `tomorrow 9am`.
- Configurable shortcut.
- Small tray indicator.


## v18 Browser OAuth + config rework

Built from the confirmed working v4 input code.

Changes:
- Main task input behaviour is untouched.
- Normal titlebar is kept.
- Esc quits the app cleanly.
- Super+T toggles open/close through the installed launcher.
- Settings has no text-entry dialogs anymore.
- Create List and Change Shortcut now use the main input field.
- Google connect opens browser OAuth automatically once `~/.config/taskpop/google_client_secret.json` exists.
- If the OAuth client file is missing, TaskPop opens the config folder and writes `GOOGLE_SETUP.md`.

Main input command mode:
- `:list Work`
- `:shortcut <Super>t`
- `:google`
- `:sync`
- `:local`

Google setup:
1. Create a Google Cloud OAuth Client ID with Application type = Desktop app.
2. Download the JSON file.
3. Save it as `~/.config/taskpop/google_client_secret.json`.
4. In TaskPop, use Settings → Connect Google Tasks, or type `:google` and press Ctrl+Enter.


## v19 list cycling fix

Fix:
- Ctrl+Tab now cycles through all lists in a stable order.
- The list order is now based on creation order instead of last-used/updated time.
- This prevents the current and previous list from constantly jumping to the top and causing a two-list loop.

No database reset is required.


## v20 command mode

Changes:
- Typing `:` shows available commands in the task list area.
- Unknown text starting with `:` is no longer added as a task.
- Added `:unlist` to remove the current local list.
- `:unlist` will not remove the only remaining list.
- `:unlist` blocks Google-synced lists for now to avoid accidental remote/local mismatch.


## v22 Google sync thread fix

Fix:
- Google login/token was working, but sync failed because the background sync thread was using the UI thread's SQLite connection.
- Sync now opens its own SQLite connection inside the worker thread.
- This should allow Google Tasks lists and tasks to pull into the local database and then refresh the UI.


## v23 TaskPop icon

Changes:
- Added the supplied `taskpop.png` icon without changing the design.
- Installer now installs hicolor icon sizes from 16x16 through 512x512.
- Desktop launcher now uses `Icon=taskpop`.
- Desktop file is installed as `com.dsynz.TaskPop.desktop` to better match the GTK application ID.
- Added `install_icon_only.sh` for updating only the icon later.
