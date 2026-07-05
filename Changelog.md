# Changelog

## v29-test

Test build. Do not push until verified.

- Added task editing with `Shift+Enter` and `Ctrl+E`.
- Added `Ctrl+L` to rename current list.
- Added `Ctrl+C` to copy selected task text.
- Added `Ctrl+S` to open Settings.
- Added `Ctrl+K` to clear completed tasks.
- Added `Ctrl+1` … `Ctrl+9` to jump to visible list numbers.
- Added `Ctrl+0` to jump to the last visible list.
- Made Clear and Settings buttons smaller and square.
- Split README and changelog.

## v28-test

- Primary Google Tasks list delete/convert now shows a warning instead of hiding it.
- Added `:convert-to-local` and `:convert-to-google-task` aliases.
- Added list ordering commands: `:reorder`, `:order-az`, `:order-za`, `:order-lg`, `:order-gl`.
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
