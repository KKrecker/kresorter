# 0018. The owner's requests after step 8: the theme, a restart, select all, motion, speed, the zones, what a cache is, focus, grouping by meaning, the model, the AI on the Overview, a security audit

- Status: accepted
- Date: 2026-11-04
- Builds on: 0004 (item 5), 0005, 0010 (items 11-15), 0012, 0013, 0014, 0016
- Amends: 0010 item 11 (a cache is likely safe; a browser's cache is for review), 0013 items 3,
  5, 6, 9 and 21 (the model's answer may group files into a plan the user confirms; the names
  of those files are sent; the model can be chosen in the window), 0014 items 19, 27, 32, 34
  and 35 (the safe zones can be left out, the language applies after a restart, a list is
  ringed only when the keyboard focused it, the theme can be chosen, `settings.json` has three
  more keys), 0005 (a scan asks `/proc` once)

## Context

After using the Windows build, the owner asked for thirteen things: a light and dark switch in
the window; a restart offered when the language changes; Select all in the quarantine; a
smoother window; a faster scan; leaving `~/.cache` or `~/Downloads` out of the scan; not
calling a cache safe; no blue ring around a list that was clicked; whether the local AI can
group files by what their names mean; what authoritative sources say may be deleted without
loss; a choice of the local AI's model, with one recommended for the machine; a card about the
local AI on the Overview; and a security audit of the whole program.

**What the sources say about caches.** Every source agrees that a cache is rebuilt by the
program that made it, and that it holds copies, not the user's data:

- The XDG Base Directory Specification: `$XDG_CACHE_HOME` (default `~/.cache`) is "the base
  directory relative to which user-specific non-essential data files should be stored"
  (<https://specifications.freedesktop.org/basedir-spec/latest/>).
- Python's tutorial (6.1.3): Python caches the compiled version of each module in
  `__pycache__`, checks it against the source and recompiles; "This is a completely automatic
  process" (<https://docs.python.org/3/tutorial/modules.html>); PEP 3147 defines the layout
  (<https://peps.python.org/pep-3147/>).
- Microsoft's Disk Cleanup selects "Downloaded Program Files, Temporary Internet Files, and
  Thumbnails" by default, and Storage Sense removes "temporary files" and, only when the user
  sets it up, files in Downloads
  (<https://support.microsoft.com/en-us/windows/disk-cleanup-in-windows-8a96ff42-5751-39ad-23d6-434b4d5b9a68>,
  <https://support.microsoft.com/en-us/windows/manage-drive-space-with-storage-sense-654f6ada-7bfc-45e5-966b-e24aded96ad5>).
- The freedesktop Thumbnail Managing Standard: a thumbnail is deleted when its original is
  gone, and a tool may delete them all; they are made again from the originals
  (<https://specifications.freedesktop.org/thumbnail-spec/latest/delete.html>).
- Apple: `.DS_Store` holds the Finder's view of a folder (its sorting, its icons), which the
  Finder reads and writes; it can be told not to write them on network shares at all
  (<https://support.apple.com/en-us/102064>).

**A browser's cache.** The owner holds that a browser's cache cannot be deleted without loss.
The browsers' own help says what is lost, and it is not the sign-ins: Chrome, "Cached images
and files: Chrome remembers parts of pages to help them open faster during your next visit",
while "Cookies and other site data" hold the sign-ins
(<https://support.google.com/chrome/answer/2392709>, and "if you were signed in, you'll need
to sign in again" after clearing cookies, <https://support.google.com/accounts/answer/32050>);
Mozilla, "The Firefox cache temporarily stores images, scripts, and other parts of websites
you visit in order to speed up your browsing experience", while cookies "contain information
such as site preferences and login status"
(<https://support.mozilla.org/en-US/kb/how-clear-firefox-cache>,
<https://support.mozilla.org/en-US/kb/clear-cookies-and-site-data-firefox>); Microsoft Edge,
"Cached images and files: Copies of pages, images, and other media content stored on your
device", sign-in info being among the cookies and site data
(<https://support.microsoft.com/en-us/microsoft-edge/view-and-delete-browser-history-in-microsoft-edge-00cf7943-a9e1-975a-a33d-ac10ce454ca4>).
kresorter's rules match only those cache directories (`Cache`, `Code Cache`, `GPUCache`,
`cache2`), never cookies, `Local Storage`, `IndexedDB` or `Service Worker` (a web app's offline
data is site data). What is lost is time and traffic: every page loads from the network once
more, and a browser that is running may be using its cache (the open-file check sees what it
holds open, not what it will open next). So the owner's request is taken, for that reason
rather than for the sign-ins: a browser's cache is shown for review, never proposed; every
other cache is likely safe, so nothing rebuilt by another program is preselected; thumbnails
and the Finder's metadata stay safe.

**Speed.** On this machine a made-up tree of 20,000 files (662 MB) took 6.1 s to scan with the
`/proc` check and 2.1 s without it: `ProcFdChecker` lists every process's descriptors for every
file, so a desktop with hundreds of processes pays it 20,000 times. The rest is the classifier
(about 60 % of what is left: every glob of every rule against every directory of every file),
the policy asked again for each file, and hashing.

**Grouping by meaning.** Yes: a local model can read file names and propose folders by what
they mean ("Taxes 2024", "Trip to Kazan"). It is the first time the model's answer shapes a
plan, so the boundaries of 0013 are moved only as far as that needs: the names are sent, the
answer is checked as untrusted input, and what it yields is a plan like any other, which
organize's own rules check and the user confirms.

Every numbered item below is a behaviour a test can show, and is cited by one (item 44).

## The theme (request 1)

1. **A theme setting.** `settings.json` has `theme`, `system`, `light` or `dark`, `system` when
   left out; any other value is a wrong value (0014 item 36). The Settings page has a card
   Appearance with a choice of System, Light and Dark.
2. **Chosen, applied at once.** `system` follows Qt's colour scheme as 0014 item 34 says;
   `light` and `dark` use their palette whatever the system says, and a change of the system's
   scheme then changes nothing. A change is saved and applied at once, and the window opens in
   the theme remembered.

## The language (request 2)

3. **A change offers a restart.** Once a new language is saved, a confirmation asks whether to
   restart the window now to apply it (Restart now); declined, the language applies the next
   time the window opens, as the note says.
4. **The window's restart, in the same process.** Restart closes the window as closing does
   (0014 item 17: it waits for a task that acts); once it is closed, `ui.app.run` opens a new
   window, with the settings read again and the new language, on the same page. No program is
   launched (0014 item 7). A window closed otherwise ends the application.

## Select all in the quarantine (request 3)

5. **Select all and Clear.** The Quarantine page has Select all, which checks every row, and
   Clear, which unchecks them; Restore and Delete permanently act on the checked rows after
   their confirmations, as before.

## Motion (request 4)

6. **A page fades in.** A page that opens fades in over `motion.DURATION_MS` (150 ms); it is
   usable at once, and the effect is removed when it ends.
7. **A switch slides.** A switch that turns moves its knob to its side over the same time; its
   state is the new one at once, only its drawing moves.
8. **Hover.** A button, a chip and a card that opens a page show the pointer over them: a
   button on `surface 2` (a primary button on `accent`), a chip and a card with an `accent`
   border; colours of the tokens only (0014 item 32).
9. **A scan shows that it works.** While a scan runs, the scan card shows a moving bar and the
   window's status line the files read so far, at most ten times a second.
10. **Motion can be off.** With `motion.DURATION_MS` at 0 nothing moves and the end is drawn at
    once; the screenshots use it.

## Speed (request 5)

11. **One look at `/proc` per scan.** A scan on Linux lists the open files of every process it
    may read once, at its start: a file is open for the scan when its `(st_dev, st_ino)` is
    among them. A file opened after that look is not seen by the scan; preflight still asks
    `/proc` afresh for each file right before it acts (0004 item 5), so nothing is moved on the
    scan's word. A `/proc` that cannot be listed makes every file open (fail closed).
12. **Windows checks side by side.** The share-mode checks (0016) of a directory's files run in
    up to eight threads; each file's answer is its own and the events keep the order of
    before, whichever check ends first.
13. **Rules matched once per directory.** The classifier decides once per directory which
    rules its directories match, and per file only the file-name globs; a glob segment without
    `*`, `?` or `[` is compared by equality. Every path gets the rule it got before.
14. **The policy asked once per directory.** A file in a directory the walker allowed is
    checked by its name alone, with the same answer as `check_path` on its path.
15. **Hashing side by side.** The prefixes and the full digests of the duplicate candidates are
    computed in up to four threads; the groups, their order and the skipped paths are those of
    before.
16. **The scan reports its progress.** `scan` takes an optional callback, called with the
    files read so far at least every 1,000 files and at the end; the window's scan uses it.

## The zones (request 6)

17. **A safe zone can be left out.** Each safe zone's chip has a remove button, as an added
    folder's has; a zone left out is not scanned, and the window remembers it: `settings.json`
    has `skipped_zones`, the names of the zones left out (`.cache`, `Downloads`: a zone's last
    part, never a path, 0014 item 35); a name of no zone is a wrong value.
18. **And put back.** A zone left out has a link of its own, "+ ~/.cache", at the end of the
    folders; it puts the zone back where it was and saves. With no folder at all, Scan now is
    disabled.

## What a cache is (requests 7 and 10)

19. **A cache is likely safe.** `junk_cache` is `LIKELY_SAFE`: never preselected (0014 item 4),
    still proposed. Thumbnails and the folder metadata of the systems stay `SAFE`.
20. **A browser's cache is for review.** A junk category of its own, `browser_cache` (evidence
    `junk_browser_cache`), at `REVIEW`: never proposed, never moved in bulk (0010 item 15), and
    in the window checked only by the user. Its rules come before the others: `chromium-cache`
    and `firefox-cache` on Windows as before, Opera's
    `AppData/Local/Opera Software/*/Cache`, `inet-cache`, and on Linux the caches of Chrome,
    Chromium, Firefox, Brave, Edge, Opera, Vivaldi and Yandex under `~/.cache`.
21. **Named in both languages**, in the window (the evidence) and in `analyze` (the category).
22. **The README says it.** Its section on levels says that a cache is likely safe, that a
    browser's cache is for review and why, and links this decision.

## Focus (request 8)

23. **A list is ringed only when the keyboard focused it.** A list or tree focused by Tab,
    Backtab or a shortcut has the accent border until it loses focus; one focused by a click
    has none (its selected row says where it is). Buttons, fields and choices keep their ring.

## Grouping by meaning (request 9)

24. **Asked only on request.** Once a plan is shown, the Organize page has Group by meaning
    (local AI); nothing is sent before it is pressed, and nothing when the plan has no file
    to group.
25. **Names only.** The model gets the names of the files the plan moves or keeps as
    `unknown_kind`, sorted, at most 100, each at most 100 characters (longer ones are not
    sent), with an instruction that they are data, and the window's language for the folder
    names: no path, folder, size, time or content.
26. **One answer, checked as untrusted input.** The answer is a JSON object
    `{"groups": [{"folder": ..., "files": [...]}]}` or a reason (`bad_response`); a file is
    taken only if it was sent and is named once in the whole answer; a group needs two files
    taken; at most 12 groups; anything else is ignored.
27. **A folder name is a name.** A group's folder is kept only if it is 1 to 40 characters of
    letters, digits, spaces and `-_.,()&'`, starts with a letter or a digit, ends with neither
    a space nor a dot, is no Windows device name (`CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`,
    `LPT1`-`LPT9`, with or without an extension), and differs, folded, from the folders kept
    before it; otherwise its files keep their category by kind.
28. **A plan like any other.** The groups make a new plan of the folder through organize's
    planner, each grouped file's category its group: every reason to stay of 0012 holds, and
    the new destinations are checked as any (companions, the path limit, a category blocked,
    a conflict). The page shows it as a plan, says the groups come from the local AI and may
    be wrong, and By kind goes back to the plan by kind.
29. **Sort keeps the groups.** The plan made again under the lock at Sort... (0014 item 14)
    uses the same groups; the model is not asked again; the batch is journaled and undone as
    any.
30. **Bounded.** Grouping is one `POST /api/generate` (0013 item 11) with `"format": "json"`, a
    deadline of its own (120 s) and a body of at most 32 KiB; its answer at most 64 KiB, as
    every answer.
31. **Without the model, the plan by kind.** A grouping that fails says why (0013 item 23) and
    leaves the plan by kind.

## The model (request 11)

32. **Chosen in Settings.** Check lists the models Ollama has (`GET /api/tags`) in a choice
    on the AI card; the one chosen is saved in `settings.json` as `model` (a name 0013 item 9
    accepts; left out, the default) and used by every explanation, grouping and check;
    `KRESORTER_OLLAMA_MODEL`, when set, wins, and the card says so.
33. **Recommended for the machine.** The card recommends a model from the machine's memory
    and its processors, `qwen2.5` for its languages (Russian among them): under 8 GiB
    `qwen2.5:1.5b`, under 16 GiB `qwen2.5:3b`, under 32 GiB `qwen2.5:7b`, otherwise
    `qwen2.5:14b`, one size smaller with fewer than four processors; the memory from
    `GlobalMemoryStatusEx` on Windows and `os.sysconf` elsewhere, unknown as under 8 GiB. It
    says how to get it (`ollama pull NAME`); kresorter installs nothing.
34. **The model in use is named** in the sidebar and on the card of item 35.

## The AI on the Overview (request 12)

35. **A card for the local AI.** The Overview has a fourth service card, Local AI: the model in
    use and whether the last Check found it available, unavailable, or that no check ran yet;
    a click opens Settings. The card asks nothing of Ollama (0013 item 1).

## The audit (request 13)

36. **The report.** `docs/reviews/security-audit.md` says what was checked (the network, text
    shown, file operations, the data directory, parsing, the model's answers, packaging), what
    was found and what was fixed, each fix with its test.
37. **Untrusted text is plain text.** A label that shows a name, a path, a detail of the
    system or a model's answer shows it as plain text, never as rich text; a tooltip that Qt
    would take for rich text is escaped first. A file named `<img src=x>` or `<b>x</b>` is
    shown as those characters.
38. **Nothing that runs text.** No module in `src` uses `eval`, `exec`, `compile`, `pickle`,
    `marshal`, `shelve`, `yaml.load` or `shell=True` (a guard reads the AST).
39. **The settings file is not a door.** `settings.json` is read with at most 64 KiB and
    refused beyond (`unreadable`); a link in its place is refused (`O_NOFOLLOW` when written,
    and not followed when read on POSIX).
40. **Every network point is loopback.** Every request of the window, the grouping and the model
    list among them, goes through `llm.transport` to the loopback address of 0013 item 8.

## Docs

41. **The README** says the theme, the restart, Select all, the zones left out, the model's
    choice and recommendation, grouping by meaning and what it sends, and the Local AI card.
42. **The changelog** of 0.1.0 says the same, for its users.
43. **The roadmap** records this decision's work and its accepted limitations.

## The meta-test

44. **Every item of this decision is cited by a test** as `[0018.N]`. A meta-test fails on an
    item no test cites, on a citation of an item that does not exist, and on an item still
    listed as pending although a test cites it; the pending list starts with every item and is
    empty after the last commit of this decision's plan. The meta-test checks the rules of
    `tests/support/decisions.py` on made-up items and citations, and that check cites this
    item.

## Plan

Each line is one commit or one test/fix pair (red, then green). The items in brackets leave
the pending list in that commit, and no earlier test cites them.

1. This decision and its meta-test, every other item pending [44].
2. A list ringed only from the keyboard [23].
3. Select all and Clear in the quarantine [5].
4. A cache likely safe, a browser's cache for review, their labels [19-21].
5. One look at `/proc` per scan [11].
6. Rules once per directory, the policy once per directory [13, 14].
7. Checks and hashing side by side; the scan's progress [12, 15, 16].
8. The zones left out and put back [17, 18].
9. The theme [1, 2].
10. The restart [3, 4].
11. Motion and the scan's bar [6-10].
12. The model: its choice and recommendation, named [32-34].
13. The Local AI card [35].
14. Grouping by meaning [24-31].
15. The audit: plain text, no runner of text, the settings file, loopback; the report [36-40].
16. The README, the changelog, the roadmap [22, 41-43].

## Accepted limitations

- **The scan's look at `/proc` is a moment**: a file opened during a long scan is reported as
  not open; preflight checks it again before anything acts.
- **A browser's cache is never proposed**, though the browsers say it holds no sign-ins: it
  is the owner's choice, made for the time and traffic it costs.
- **The model can be wrong**: a group may not fit its files; the plan is shown before
  anything moves, and every batch can be undone.
- **The names leave kresorter for the model**, on loopback only, when the user asks: the model
  and Ollama are the user's own.
- **The recommendation is a rule of thumb** for memory and processors; it reads no graphics
  card.

## The owner's answers

- The thirteen requests, how each is done is this decision's (2026-11-04).
