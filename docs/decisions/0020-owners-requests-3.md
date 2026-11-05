# 0020. The owner's requests after trying 0.1.0: a grouping that is read, more sorted, more cleaned without losing a sign-in, a faster scan

- Status: accepted
- Date: 2026-11-05
- Builds on: 0002, 0010, 0012, 0013, 0016, 0018, 0019
- Amends: 0013 item 11 (a body says `"think": false`), 0018 items 11, 12 and 25-31 (the
  open-file check of a scan; grouping in numbered batches), 0018 item 33 and 0019 items 8 and
  13 (the models recommended; the schema of a grouping's answer)

## Context

Trying the Windows build of 0.1.0, the owner asked for four things. Group by meaning ended in
"Not grouped: the answer is not read: the answer is not {"groups": [...]}. The plan by kind
stays.", and much was left unsorted: the grouping should do better, with a larger model if
need be, by kind too (zip, exe). Kresorter should clean more (the owner's list: Windows
Update's downloads, Prefetch, the graphics drivers' shader caches), after a study of what can
be deleted and what cannot, without losing a session. And the scan should be nearly instant,
as WizTree's is.

**Why the answer was not read.** Ollama's context is 4096 tokens unless set otherwise
(<https://github.com/ollama/ollama/blob/main/docs/faq.mdx>), and LM Studio loads a model with
4096 too. A grouping sent up to 100 names, about 2,500 tokens, and asked for an answer that
names every grouped file again: together more than the context holds. Ollama then cuts the
prompt from its start, the instruction first, or the answer stops in the middle of its JSON;
either way it is not `{"groups": [...]}`. Three things made it worse: `"format": "json"` asks
for any JSON object, not this one; a thinking model (Qwen3, DeepSeek-R1) thinks first unless
`"think": false` is sent (Ollama's `server/routes.go`: a model that can think thinks when
`think` is not set), and its thinking spends the same budget; and the small models
recommended under 16 GiB (`qwen2.5:1.5b`, `qwen2.5:3b`) copy long names wrongly, and a name
not copied exactly was not taken, so its file stayed unsorted.

**Why much stays unsorted.** The table of kinds (0012 item 21) knows 6 kinds and 70
extensions; any other extension stays (`unknown_kind`), and so does every file that shares its
stem with it (companions, 0012 item 14): `film.mkv` stays with `film.srt`.

**What the scan spends its time on.** Measured on a GitHub Windows runner (`windows-latest`,
Python 3.13, Defender's real-time protection off, a second scan with the files' metadata
in memory), on the 190,433 files of `C:\hostedtoolcache\windows`:

| What | Seconds |
|---|---|
| `os.scandir` alone, every directory | 2.2 |
| The scan without the open-file check, without hashing | 9.8 |
| The scan with the open-file check, without hashing | 32.9 |
| The scan without the open-file check, with hashing | 154.5 |

The share-mode check (0016) opens every file the scan lists: two thirds of a scan without
hashing, and more where an antivirus looks at each file opened. Hashing the files that share
their size is the rest; listing is the least of it.

**WizTree** reads NTFS's Master File Table itself: the volume opened as `\\.\C:`, its boot
sector read for where the table lies, then the table read in long runs, one 1 KiB record per
file with its name, its parent, its times and its size, the tree built in memory. It needs an
administrator and NTFS; without them it lists directories as any program does. The same read
in Python, on the runner's `C:` (1,361,152 records): 15.0 s, 7.7 of them reading, and 2.5 s more
to make the paths. It pays for a whole volume, which kresorter never scans: for the folders it
scans, listing costs 2.2 s of the 33, and the MFT would not make the open-file check or the
hashing any cheaper. Kresorter keeps listing directories; the time goes from where it is spent
(items 19-22).

## Grouping that is read (request 1)

1. **Batches a small context holds.** The names of 0018 item 25 (the files the plan moves or
   keeps as `unknown_kind`, sorted, each at most 100 characters) are sent in batches, each at
   most 40 names and 2,000 bytes of names in UTF-8, at most 10 batches (400 names); each
   batch's body is at most `group_bytes` (32 KiB) as before. A batch, its instruction and its
   answer fit in 4096 tokens.
2. **Numbered.** A batch's prompt is `{"language": ..., "folders": [...], "files": {"1":
   "<name>", "2": "<name>", ...}}`, its files numbered from 1. The answer is
   `{"groups": [{"folder": "...", "files": [1, 4, 7]}]}`: a number names the file it was
   given to; a file is taken when it is named once in the batch's answer, by its number or by
   its exact name.
3. **The answer's shape asked of both servers.** Ollama gets the answer's JSON schema as
   `"format"` (structured outputs, Ollama 0.5.0 and later; an earlier version, or a version
   that is not `N.N.N`, gets `"json"`), LM Studio the same schema in `response_format`
   (0019 item 8), the files a list of integers. `num_predict` and `max_tokens` are 1024.
4. **No thinking.** Every body sent to Ollama, a grouping's and an explanation's, says
   `"think": false`: a model that thinks answers at once, and Ollama refuses `think` only
   when it is `true` for a model that cannot think.
5. **Read as it comes.** The answer is read from the JSON object itself, or from the one in a
   fenced block (```` ``` ````), or from its first `{` to its last `}`; its `groups` is a list
   of objects as asked, or an object whose keys are folders and whose values are lists of
   files. Anything else is `bad_response`, the reason quoting the answer's first 60
   characters on one line, as cleaned for the window (0013 item 20).
6. **A cut answer says so.** An answer Ollama ended for its length (`done_reason`
   `"length"`), or LM Studio (`finish_reason` `"length"`), is `bad_response`: `the answer was
   cut at its length`, so the reason says what to change (a model's context, fewer files).
7. **One grouping of the batches.** Each batch gets the folders kept so far as `"folders"`
   and is asked to use one of them when its files belong there; folders that are equal folded
   (0018 item 27) are one group. When every batch has answered, a group needs two files, and
   at most 24 groups are kept, in the order their folders came.
8. **A batch that fails ends the grouping.** The groups of the batches before it are kept;
   the note says how many files were grouped and why the grouping stopped. When the first
   batch fails, the plan by kind stays, as before (0018 item 31). Each batch has the deadline
   of 0018 item 30 (120 s).
9. **The instruction** (0018 item 25) asks for as many files as can be grouped: by project,
   trip, event or subject, or else by what they are (drivers, receipts, game mods); a group
   of at least two files; a folder of `"folders"` when the files belong there; each file in
   one group at most, the files that fit none left out; a folder's name a few plain words in
   the language given, at most 40 characters.
10. **The note says what was grouped**: `The local AI grouped N of M files into K folders.`,
    under the plan made with the groups.

## The model (request 1, a larger model)

11. **Qwen3 recommended.** The recommendation of 0018 item 33 is Qwen3, which answers in
    Russian too and comes as instruct models that do not think: under 8 GiB `qwen3:1.7b`,
    under 32 GiB `qwen3:4b-instruct`, otherwise `qwen3:30b-instruct` (a mixture of experts
    with 3B active parameters: on a processor about as fast as a 3B model), one size smaller
    with fewer than four processors; in LM Studio `qwen/qwen3-1.7b`, `qwen/qwen3-4b-2507` and
    `qwen/qwen3-30b-a3b-2507`.

## More sorted by kind (request 1, by kind)

12. **More kinds.** The table of 0012 item 21 gains:
    - Images: `avif`, `jxl`, `ico`, `cr3`, `raf`, `orf`, `rw2`, `psd`, `xcf`, `kra`;
    - Videos: `3gp`, `flv`, `m2ts`, `mts`, `vob`, `ogv`, and the subtitles `srt`, `ass`,
      `ssa`, `vtt`, so that a film and its subtitles go together;
    - Audio: `aiff`, `aif`, `mid`, `midi`, `ape`, `amr`, `mka`, and the lyrics `lrc`;
    - Documents: `djvu`, `fb2`, `mobi`, `azw3`, `xps`, `oxps`, `pages`, `numbers`;
    - Archives: `cab`, `lz`, `lzma`, `zipx`, `tar.lz`;
    - Installers: `msix`, `msixbundle`, `appx`, `appxbundle`, `apk`, `xapk`;
    - and three kinds of their own, after the others: Torrents (`torrent`), Fonts (`ttf`,
      `otf`, `woff`, `woff2`) and 3D models (`stl`, `3mf`, `step`, `stp`, `fbx`, `glb`,
      `gltf`, `blend`).

    Code, data and settings (`py`, `json`, `ini`, `bat`, ...) and virtual machines' disks stay
    out: they are often part of what is beside them.

## Cleaned, without losing a session (request 2)

13. **A session is never touched.** What keeps a sign-in, a saved password or the open tabs
    is blocked by the policy like a system file (a new reason, `session`): never a candidate,
    not even named by hand, and its directories are not listed. In a Chromium profile
    (Chrome, Edge, Brave, Vivaldi, Opera, Yandex): `Network`, `Cookies`, `Login Data`,
    `Login Data For Account`, `Web Data`, `Local Storage`, `Session Storage`, `Sessions`,
    `IndexedDB`, `Service Worker`, `Extensions`, `Local Extension Settings`, `Extension
    State`, `Sync Extension Settings`, `Preferences`, `Secure Preferences`, `Bookmarks`,
    `History`, `Current Session`, `Current Tabs`, `Last Session`, `Last Tabs`, and the user
    data's `Local State`, which holds the key its cookies and passwords are encrypted with;
    in a Firefox profile: `cookies.sqlite`, `logins.json`, `key4.db`, `cert9.db`,
    `places.sqlite`, `formhistory.sqlite`, `permissions.sqlite`, `sessionstore.jsonlz4`,
    `sessionstore-backups`, `storage`, `webappsstore.sqlite`, `prefs.js`, `extensions`; on
    Windows: `Microsoft/Windows/INetCookies`, `Microsoft/Windows/WebCache`,
    `Microsoft/Credentials`, `Microsoft/Protect`, `Microsoft/Vault`, `Microsoft/TokenBroker`,
    `Microsoft/IdentityCache`, `Packages/Microsoft.AAD.BrokerPlugin_*`; and Telegram
    Desktop's `tdata`, Steam's `config`. The list is data (`core/sessions.toml`), each entry
    with an example a test checks.
14. **More caches.** New rules, on Windows: the graphics drivers' shader caches (NVIDIA
    `AppData/Local/NVIDIA/DXCache`, `GLCache`, `AppData/LocalLow/NVIDIA/PerDriverVersion/DXCache`,
    `GLCache`; AMD `AppData/Local/AMD/DxCache`, `DxcCache`, `GLCache`, `VkCache`; Intel
    `AppData/LocalLow/Intel/ShaderCache`; DirectX `AppData/Local/D3DSCache`), a cache likely
    safe: rebuilt by the driver, a game may stutter while it is; the browsers' shader caches
    (`User Data/ShaderCache`, `GrShaderCache`, `GraphiteDawnCache`, `User Data/*/DawnCache`,
    `DawnGraphiteCache`, `DawnWebGPUCache`), a browser's cache; and Windows Error Reporting's
    reports (`AppData/Local/Microsoft/Windows/WER/ReportArchive`, `ReportQueue`), crash
    dumps.
15. **Programs' caches, a zone.** On Windows the Overview has one more zone, Programs'
    caches: the directories of the rules that live under `AppData\Local` and
    `AppData\LocalLow` (the browsers' caches, the shader caches, the internet cache, the
    thumbnail cache's directory, the crash dumps, the error reports) that exist when the scan
    starts. It is left out and put back like any zone (0018 item 17), by the name `caches`.
    Its files are read for junk only: they are not compared as duplicates and not shown as
    large or old.
16. **What kresorter leaves to Windows.** `C:\Windows` and `C:\ProgramData` stay blocked
    (0002): Windows Update's downloads (`SoftwareDistribution\Download`), the system's temp,
    `Prefetch`, `WinSxS`, `Windows.old`, the memory dumps, Delivery Optimization's cache,
    `hiberfil.sys` and `pagefile.sys`. They need an administrator, some are in use while
    Windows runs, and Windows cleans them itself, safely: Settings > System > Storage >
    Temporary files, or Disk Cleanup > Clean up system files. Prefetch is not to be cleaned:
    Windows keeps it small and rebuilds it, and a program starts slower until it has. The
    README says so, and why.

## A faster scan (request 3)

17. **The open-file check only where it decides something.** A scan lists without opening
    any file. Once the junk is classified and the duplicates hashed, the junk files and the
    copies of each duplicate group are checked for being open, eight at once on Windows (0018
    item 12), the snapshot of open files on Linux (0018 item 11); an open one is skipped as
    before (`blocked`, `open_file`) and leaves its group, and a group left with one copy is
    none. Any other file is not checked by the scan: a large or old one, shown for review, is
    checked when it is acted on (preflight, 0006).
18. **Digests kept while the window is open.** The window keeps each hashed file's prefix and
    full digest with its path, size and `mtime_ns`; a later scan in the same window reads the
    content of no file that is unchanged.
19. **The time said.** The Findings page says how long the scan took and what took it:
    `Scanned in 9.8 s: listing 2.1 s, open-file checks 0.4 s, duplicates 7.3 s.`
20. **The MFT is not read.** Kresorter lists directories (Context): it never asks for an
    administrator, it scans folders and not volumes, and it does not depend on NTFS. A whole
    drive's map, as WizTree draws it, is not its work.

## Docs

21. **The README**, in both languages, says how grouping works now (batches, numbers, the
    recommended models, the context), the kinds added, what is cleaned and what is never
    touched for the sessions, what is left to Windows and why, and what a scan spends its
    time on.
22. **The changelog** of 0.1.0 says the same, for its users.
23. **The roadmap** records this decision's work and its accepted limitations.

## The meta-test

24. **Every item of this decision is cited by a test** as `[0020.N]`, with the rules of
    `tests/support/decisions.py` (0019 item 24); the pending list starts with every item and
    is empty after the last commit of this decision's plan.

## Plan

Each line is one commit or one test/fix pair (red, then green). The items in brackets leave
the pending list in that commit, and no earlier test cites them.

1. This decision and its meta-test, every other item pending [24].
2. Grouping in numbered batches, with the schema, without thinking, read as it comes [1-8].
3. The instruction and the note [9, 10].
4. Qwen3 recommended [11].
5. More kinds [12].
6. The sessions blocked [13].
7. More caches; the zone of programs' caches [14, 15].
8. The open-file check where it decides; the digests kept; the time said [17-19].
9. The README, the changelog, the roadmap [16, 20-23].

## Accepted limitations

- **A small model still groups less**: the batches and the numbers make its answer short and
  readable, not wise. The plan is shown before anything moves and a batch can be undone.
- **A grouping takes longer**: up to 10 requests instead of one, each short.
- **A file kept open by a program is found by a scan** when it is neither junk nor a
  duplicate (a large or old one, shown for review): the check comes when it is acted on.
- **Digests are kept in memory only**: the first scan after the window opens hashes again.
- **Firefox and the other browsers' session lists are by name**: a browser that adds a store
  of its own is not protected until the list says so; a cache rule never names one.
- **The system's own folders are Windows' to clean** (item 16).
- **No MFT** (item 20): a scan of a large folder still lists it directory by directory.

## The owner's answers

- The four requests and the screenshot of the failed grouping (2026-11-05); how each is done
  is this decision's.

## Appendix: what can be cleaned on Windows

| Where | What it is | Kresorter |
|---|---|---|
| `%LOCALAPPDATA%\Temp` | Programs' temporary files; an installer may still need its own | Junk (temp), scanned when chosen (0002) |
| `C:\Windows\Temp` | The system's temporary files | Left to Windows (item 16) |
| `C:\Windows\SoftwareDistribution\Download` | Updates downloaded by Windows Update; removed safely only when no update is pending, with the service stopped | Left to Windows: Temporary files, Windows Update Cleanup |
| `C:\Windows\Prefetch` | Windows' notes for starting programs faster, kept small | Not to be cleaned: rebuilt, programs start slower meanwhile |
| `C:\Windows\WinSxS` | The components store; most of its size is hard links to files in use | Left to Windows (`DISM /Cleanup-Image /StartComponentCleanup`) |
| `C:\Windows.old` | The previous Windows after an upgrade, needed to go back | Left to Windows: Previous Windows installation(s) |
| `C:\Windows\MEMORY.DMP`, `Minidump`, `LiveKernelReports` | The system's crash dumps | Left to Windows: System error memory dump files |
| Delivery Optimization's cache | Updates shared with other PCs | Left to Windows: Delivery Optimization Files |
| `hiberfil.sys`, `pagefile.sys` | Hibernation, virtual memory | Never (in use) |
| `C:\$Recycle.Bin` | The Recycle Bin | Never: emptied by its owner |
| `%LOCALAPPDATA%\NVIDIA\DXCache`, `GLCache`; `AppData\LocalLow\NVIDIA\PerDriverVersion` | NVIDIA's shader cache | Junk (cache, likely safe; item 14) |
| `%LOCALAPPDATA%\AMD\DxCache`, `DxcCache`, `GLCache`, `VkCache` | AMD's shader cache | Junk (cache, likely safe; item 14) |
| `AppData\LocalLow\Intel\ShaderCache`, `%LOCALAPPDATA%\D3DSCache` | Intel's and DirectX's shader caches | Junk (cache, likely safe; item 14) |
| `C:\ProgramData\NVIDIA Corporation\NV_Cache` | NVIDIA's older shader cache, the system's | Left to the driver's settings |
| A browser's `Cache`, `Code Cache`, `GPUCache`, shader caches; Firefox's `cache2` | Copies of pages, scripts and shaders | Junk (browser cache, for review; 0018 item 20) |
| A browser's cookies, logins, local storage, sessions, `Local State` | Sign-ins, saved passwords, open tabs | Never (item 13) |
| `%LOCALAPPDATA%\Microsoft\Windows\INetCache` | The internet cache of Windows' own components | Junk (browser cache) |
| `%LOCALAPPDATA%\Microsoft\Windows\INetCookies`, `WebCache` | Their cookies and history | Never (item 13) |
| `%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db` | Explorer's thumbnails | Junk (thumbnails, safe) |
| `%LOCALAPPDATA%\CrashDumps`, `Microsoft\Windows\WER` | Programs' crash dumps and error reports | Junk (crash dump, likely safe; item 14) |
| `%APPDATA%\Microsoft\Credentials`, `Protect`, `Vault`; `TokenBroker`, `IdentityCache`, the AAD broker | Saved credentials, the keys that open them, the Microsoft account's sign-in | Never (item 13) |
| Telegram Desktop's `tdata`, Steam's `config` | Their sign-in | Never (item 13) |
| `%APPDATA%` (Roaming) | Programs' settings, travelling with the profile | Never (0002) |
