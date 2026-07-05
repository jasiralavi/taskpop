# Changelog

## v0.3.1

- Fixed Google Tasks sync getting stuck when a previously synced Google task was deleted remotely.
- TaskPop now recreates the missing Google task instead of staying at `Offline · pending`.


## v34-test

Test build. Do not push until verified.

- Fixed Google sync 404 errors when a synced task was deleted in Google Tasks outside TaskPop.
- Missing remote Google tasks are recreated on sync instead of leaving TaskPop in `Offline · pending`.
- If the remote Google list is missing, TaskPop recreates the list and updates the local mapping.


## v33-test

Test build. Do not push as final until verified.

- Cleaned up README for v0.3.0 release.
- Updated keyboard shortcut documentation.
- Updated command documentation.
- Confirmed Google Tasks date/time limitation note.
- Prepared source package for clean install and release push.

## v32-test

- Fixed Google sync overwriting TaskPop due time with midnight.
- Google sync now sends due date only, while TaskPop preserves local due time and reminders.

## v31-test

- Changed `Shift+Enter` to open the full task details panel.
- Changed Settings shortcut to `Ctrl+O`.
- Changed `Ctrl+S` to save/sync depending on context.
- Fixed notes field Tab behavior.
- Improved time-only parsing.
- Clarified Google Tasks due date/time behavior.

## v30-test

- Added task details panel with `Ctrl+D`.
- Added task details / notes.
- Added smart date and time parsing.
- Added date/time display settings.
- Added reminder fields in task details panel.

## v29-test

- Added task editing with `Shift+Enter` and `Ctrl+E`.
- Added `Ctrl+L` to rename current list.
- Added `Ctrl+C` to copy selected task text.
- Added `Ctrl+S` to open Settings at the time.
- Added `Ctrl+K` to clear completed tasks.
- Added `Ctrl+1` … `Ctrl+9` to jump to visible list numbers.
- Added `Ctrl+0` to the last visible list.
- Made Clear and Settings buttons smaller and square.
- Split README and changelog.

## v28-test

- Primary Google Tasks list delete/convert now shows a warning instead of hiding it.
- Added `:convert-to-local` and `:convert-to-google-task` aliases.
- Added list ordering commands.
- Improved command filtering.
- Prevented disabling both Local Lists and Google Tasks.

## v27-test

- Added fallback handling for Google list delete refusal.

## v26-test

- Selected task/command stays visible while navigating.
- Added brush button and `:clear`.
- Completed tasks remain visible and move to the bottom.
- Added source enable/disable commands.

## v25-test

- Kept local lists and Google Tasks lists separate.
- Added local/Google list commands and source toggles.

## v24-test

- Improved command list navigation.
- Added list source icons and top bar layout changes.

## v23

- Added custom TaskPop app icon.
- Installed hicolor icons and desktop launcher icon.

## v22

- Fixed Google sync SQLite threading issue.

## v20

- Added command mode and `:unlist`.

## v19

- Fixed Ctrl+Tab list cycling.

## v18

- Added browser-based Google OAuth flow.

## v4

- Stable base for typing, navigation, task add, and tick/untick behavior.
