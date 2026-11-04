# Security audit

- Status: accepted
- Date: 2026-11-04
- Base: `2c51063` (decision 0018's step 14, grouping by meaning), its gate green on Python
  3.11, 3.13 and 3.14
- Asked by: the owner's request 13 (decision 0018, items 36-40)

## 1. Summary

The audit read every module of `src` for what reaches it from outside kresorter: names and
paths on disk, the settings file, the system's details, Ollama's answers and the model's. It
found six defects, all fixed with a test each (F1-F6). The most serious, F1, was in the window:
every label took text that looks like HTML for rich text, so a file named `<b>x</b>` was drawn
in bold and a label given `<img src=…>` loaded and drew the image file it names (confirmed: a
label given the path of a 1280 x 800 screenshot grew to 1280 x 800). F2-F6 harden the settings
file, the lock and the one network point against what only a program already running as the
user could put there; none was reachable through the network. Two guards were added so that
what was checked stays checked: no label but a plain-text one, no tooltip that is not escaped
(item 37), and nothing in `src` that runs text (item 38).

## 2. Checked

| Area | What was checked | Result |
|---|---|---|
| The network | Which modules may connect; which addresses are asked; proxies, redirects, resolvers; deadlines; sizes of what is sent and read; that every request of the window (the Check and its model list, an explanation, the grouping) goes through `llm.transport` | One network point (`llm.transport`, `http.client` and `socket` only); loopback only, never a name; no proxy, no redirect, no resolver; one deadline per request; at most 4 KiB sent (32 KiB for the grouping) and 64 KiB read. The transport itself did not check the address it was given (F6) |
| Text shown | Every label, tooltip, dialog, list row and field of the window that can show a name, a path, a detail of the system or a model's answer | Rows, buttons, fields, lists and the dialogs' details are plain text by Qt's design; labels and tooltips were not (F1, F2) |
| File operations | What deletes, moves, writes or starts a program; links and swapped folders; files open in other programs | One deletion point (the purge), guarded; no program started; organize refuses a folder or a category directory swapped for a link, a destination taken, a file open, changed or gone since the plan. Nothing found |
| The data directory | Its place (never in a scan zone), its modes, the lock, the settings file, the temporary file | `0700` and `0600`; refused inside a zone. The settings file was read whole and through a link (F3, F4), and a FIFO in its place kept the window from opening (F5); the lock followed a link and made its target private (F4) |
| Parsing | Every JSON, TOML and binary format read: settings, Ollama's answers, the model's answers, autostart entries, the bundled tables | Every read is bounded; deep nesting is caught (`RecursionError`); the TOML tables are the package's own. No `eval`, `exec`, `compile`, `pickle`, `marshal`, `shelve`, `yaml.load` or `shell=True` anywhere (now guarded) |
| The model's answers | What an explanation shows, what a grouping takes, what the model list offers | An explanation is cleaned of escape sequences and control characters, at most six lines and 600 characters; a grouping takes only names sent, each named once, into folders whose names are names (letters, digits, a few signs, no Windows device), at most twelve; a model name is held to item 9's form. Shown as plain text only since F1 |
| Packaging | The wheel and the sdist, the entry points, the Windows folder, the installer | The wheel holds the package and nothing else, two commands; the installer is per user without administrator rights and never removes the data directory. Nothing found |

## 3. Found and fixed

### F1. Labels took a name for rich text

Every label of the window was a `QLabel` with Qt's default `AutoText`: text that looks like
HTML was drawn as HTML. A file named `<b>x</b>` was shown bold, `<i>…` in italics, and a
label given `<img src=…>` loaded the image file it names. Every label is now a `Label`
(`ui.parts`), plain text whatever it is given: 33 labels made directly, `Note`, a page's head
and the badges. A guard reads the window's modules: no `QLabel` is made but through `Label`,
no class but `Label` derives from it, no message box.

- Test: `tests/ui/test_ui_plain_text.py::test_names_and_paths_are_shown_as_those_characters_everywhere`
- Test: `tests/ui/test_ui_plain_text.py::test_a_model_s_answer_is_shown_as_those_characters`
- Test: `tests/ui/test_ui_plain_text.py::test_no_module_of_the_window_shows_text_as_rich_text`

### F2. Tooltips took a path for rich text

Qt decides alone whether a tooltip is rich text. A zone's, a batch's folder's, an autostart
entry's or the data directory's path with a tag in it was drawn as HTML. Each of the eight
tooltips now goes through `tooltip`, which escapes a text Qt would take for rich text and
leaves any other as it is; the guard checks that every `setToolTip` does.

- Test: `tests/ui/test_ui_plain_text.py::test_a_tooltip_qt_would_take_for_rich_text_is_escaped`
- Test: `tests/ui/test_ui_plain_text.py::test_the_guard_names_each_way_to_rich_text`

### F3. The settings file was read whole

`settings.json` was read with `read_bytes`, whatever its size. It is now read with at most
64 KiB and one byte, and a larger file is refused as `unreadable` (item 39).

- Test: `tests/unit/test_ui_settings.py::test_the_file_is_read_up_to_64_kib`
- Test: `tests/unit/test_ui_settings.py::test_a_larger_file_is_unreadable`

### F4. The settings file and the lock followed a link

A link in place of `settings.json` was read through, and one in place of the lock file was
opened, locked and made private (`chmod 0600` on its target). Both are now opened with
`O_NOFOLLOW` on POSIX and a link is refused; the temporary file already was, and saving
replaces a link in place of the file, never its target.

- Test: `tests/unit/test_ui_settings.py::test_a_link_in_place_of_the_file_is_unreadable`
- Test: `tests/unit/test_ui_settings.py::test_a_link_in_place_of_the_temporary_file_is_not_written_through`
- Test: `tests/unit/test_ui_settings.py::test_a_link_in_place_of_the_file_is_replaced_never_written_through`
- Test: `tests/unit/test_lock.py::test_a_link_in_place_of_the_lock_is_refused`

### F5. A FIFO in place of the settings file kept the window from opening

Opening a FIFO waits for a writer: the window never opened. The file is now opened without
waiting (`O_NONBLOCK`) and anything but a regular file is refused as `unreadable`.

- Test: `tests/unit/test_ui_settings.py::test_a_fifo_in_place_of_the_file_is_unreadable_without_waiting`

### F6. The transport trusted the address it was given

The address is checked where it is read (0013 item 8), but `llm.transport` connected to any
address it was handed. It now refuses one off loopback, or a name, before anything is made,
whatever made it (item 40). Every request of the window was followed to it: the Check and
its model list, an explanation and the grouping.

- Test: `tests/unit/test_llm_transport.py::test_an_address_off_loopback_is_never_asked`
- Test: `tests/ui/test_ui_loopback.py::test_every_request_goes_through_the_transport_to_loopback`
- Test: `tests/ui/test_ui_loopback.py::test_an_address_off_loopback_asks_nothing`

## 4. Guards kept

- No label but `Label`, no tooltip but through `tooltip`, no message box:
  `tests/ui/test_ui_plain_text.py::test_no_module_of_the_window_shows_text_as_rich_text`.
- Nothing that runs text (item 38): `tests/test_no_text_runner.py::test_no_module_runs_text`.
- One network point (0013): `tests/test_single_network_point.py::test_only_the_allowlist_imports_the_network`.
- One deletion point (0001): `tests/test_no_direct_delete.py::test_project_code_has_no_direct_deletes`.
- No program started (0013): `tests/test_no_program_launch.py::test_no_module_of_kresorter_launches_a_program`.

## 5. Left as they are

- **A link on Windows.** `O_NOFOLLOW` is POSIX's. On Windows, making a link needs a right
  the user does not have by default; the data directory is the user's own.
- **What runs as the user.** A program running as the user can change the data directory and
  kresorter's own files; the audit hardens what kresorter reads there, it cannot stop that
  program.
- **The model's answers can be wrong** (decision 0018's accepted limitations): they are shown
  as plain text and a grouping is a plan, shown before anything moves and undone as any batch.
