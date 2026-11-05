# 0019. The owner's requests after decision 0018: the answers in the window's language, the window's icon, LM Studio, a README in Russian, the release, the licence

- Status: accepted
- Date: 2026-11-04
- Builds on: 0013, 0014, 0015, 0018
- Amends: 0013 items 8, 9, 11, 14-16, 20, 23 and 26 (a second local server, LM Studio; the
  instruction names the answer's language; a reasoning model's thinking is not the answer),
  0014 item 36 (`settings.json` has `server`), 0015 items 15 and 23 (the installer shows the
  licence; the GitHub release comes first and PyPI only when the owner turns it on), 0018 item
  32 (the model chosen is the chosen server's)

## Context

After using the Windows build, the owner asked for six things: that the local AI answer in the
language set in the window (in a Russian window an explanation came in English, beginning
"Based on the JSON object"); the application's icon, missing from the window's title bar and
from the taskbar, in the portable and the installed build alike; LM Studio as well as Ollama;
the README in Russian too, with a switch at its top, English by default; a GitHub release with
the installer and the portable zip, its version written; and something done about the licence.

**Why the icon is missing.** `Kresorter.exe` carries the mark as its icon (0015 item 13), but
the window sets none. Qt on Windows then gives a window the icon of a resource named
`IDI_ICON1`, which PyInstaller does not write, and falls back to Windows' generic application
icon: the one in the title bar and on the taskbar.

**LM Studio** (<https://lmstudio.ai>) serves the models it has downloaded on
`http://127.0.0.1:1234` through an API compatible with OpenAI's: `GET /v1/models` lists them
and `POST /v1/chat/completions` answers
(<https://lmstudio.ai/docs/app/api/endpoints/openai>). It has no request that says its
version. Its structured output takes a JSON schema in `response_format`
(<https://lmstudio.ai/docs/app/api/structured-output>).

**The licence.** Kresorter is under the MIT licence already (`LICENSE`, `pyproject.toml`; 0015
item 5), and the Windows build carries Qt's and PySide6's licences and
`THIRD-PARTY-NOTICES.txt` (0015 item 13). What is missing is that it is shown: the installer
does not show it, the window does not say it, and the README says it in English only.

## The answers' language (request 1)

1. **An explanation in the window's language.** The pinned instruction (0013 item 11) ends
   with `Write the answer in <language>.`, `English` or `Russian`: the window's language (the
   one its texts are in, `system` resolved); the console's is English, its output's. It also
   says not to speak of the JSON object or of the facts, but of the item. The body's fields
   stay as they are. A grouping keeps its language (0018 item 25).
2. **A reasoning model's thinking is not the answer.** A `<think>...</think>` block at the
   start of an answer is dropped before the answer is cleaned (0013 item 20), for an
   explanation and a grouping alike, from either server.

## The icon (request 2)

3. **The window's icon is the mark.** `ui.brand` draws the mark (the sidebar's, on the accent
   tile) at any side and makes of it the application's icon, 16 to 256 px; `ui.app` sets it
   before the first window opens, so the title bar, the taskbar, Alt+Tab and every dialog show
   it, on every system.
4. **One drawing.** The ICO of `Kresorter.exe` and of the installer (0015 item 13) is made from
   `ui.brand`'s mark: its images under 256 px are uncompressed 32-bit bitmaps with their alpha,
   and its 256 px image a PNG, as Windows' icon guidelines describe.

## LM Studio (request 3)

5. **Two local servers.** `KRESORTER_LLM_SERVER` is `ollama` (when unset) or `lmstudio`; any
   other value is refused as `config`. In the window, the server chosen in Settings, unless
   the variable names one.
6. **LM Studio's address** is `KRESORTER_LMSTUDIO_URL`, `http://127.0.0.1:1234` when unset,
   with the form and the checks of 0013 item 8 (loopback only, no name resolved; 1234 when
   the port is left out).
7. **LM Studio's model** is `KRESORTER_LMSTUDIO_MODEL`, or the model chosen in the window, or
   else the first model `/v1/models` lists that is not an embedding model (no `embed` in its
   id). A model's name matches `[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}`, for either server: LM
   Studio names a quantization after `@`. A model is available when `/v1/models` lists its id
   exactly.
8. **Exactly two requests to LM Studio**: `GET /v1/models` and `POST /v1/chat/completions`,
   with the headers of 0013 item 11, never one that downloads, loads or unloads a model. An
   explanation's body is exactly

   ```json
   {"model": "<model>", "messages": [{"role": "system", "content": "<the instruction>"},
    {"role": "user", "content": "<the subject as JSON>"}], "temperature": 0, "seed": 0,
    "max_tokens": 200, "stream": false}
   ```

   and a grouping's the same with its own instruction and prompt (0018 item 25),
   `"max_tokens": 4096`, and after `stream` a `response_format` of type `json_schema` whose
   schema is `{"groups": [{"folder": "...", "files": ["..."]}]}`.
9. **What is accepted from LM Studio.** From `/v1/models`, a JSON object whose `data` is a
   list of objects with a string `id`, otherwise `not_lmstudio` (a new reason, after
   `not_ollama`); the model listed, otherwise `model_missing`, as when none is named and none
   is listed. From `/v1/chat/completions`, status 200 and a JSON object whose `choices` is a
   list whose first is an object with a `message` object whose `content` is a string,
   otherwise `bad_response`. The deadlines, bounds, budget and cleaning of 0013 (items 12, 13
   and 20) and its transport (items 7 and 10; 0018 item 40) are LM Studio's too.
10. **`kresorter llm status` with LM Studio** says `LM Studio: running at <url>` (it has no
    version to say), `Model: <model>: available`, `<model>: not available` or `none listed`;
    its steps are `Install LM Studio from https://lmstudio.ai, download a model and start its
    server (Developer, Start Server)` and `Download the model in LM Studio: <model>`. The
    settings lines of either server name `KRESORTER_LLM_SERVER` and that server's address and
    model variables, with their defaults.
11. **Named where it answers.** The explanations' header (0013 item 26) and the window's note
    say `via Ollama` or `via LM Studio`. In the window, the reasons that named Ollama name the
    local AI, and `not_lmstudio` is "It is not LM Studio".
12. **The window.** The Settings card is Local AI: a choice of server, Ollama or LM Studio,
    saved in `settings.json` as `server` (`ollama` when left out; any other value a wrong
    value, 0014 item 36); a change forgets the model chosen, which is the chosen server's, and
    runs Check. The address, the model's choice, the recommendation and the steps are the
    chosen server's; when `KRESORTER_LLM_SERVER` names a server, a note says so and the choice
    is disabled. The Overview's AI card names the server.
13. **The recommendation for LM Studio** is the same model (0018 item 33) as LM Studio names
    it, `qwen2.5-1.5b-instruct` to `qwen2.5-14b-instruct`, found in LM Studio's Discover tab.
14. **Tests** play LM Studio with the scripted server of 0013 item 29, its answers LM Studio's.

## The README in Russian (request 4)

15. **Two READMEs.** `README.md` (English) and `README.ru.md` (Russian) say the same: the same
    headings at the same levels in the same order, the same code blocks, the same images and
    the same link targets, the text translated. Each begins, under its title, with the
    switch: `**English** | [Русский](README.ru.md)` and `[English](README.md) | **Русский**`.
16. **Kept together.** The sdist carries `README.ru.md`; a test fails when the two differ in
    anything item 15 names, so what the tests of the README check holds for both.

## The release (request 5)

17. **The GitHub release first.** A tag `vX.Y.Z`, checked as before (0015 items 23 and 28),
    publishes the GitHub release `Kresorter X.Y.Z` with `Kresorter-X.Y.Z-setup.exe`,
    `Kresorter-X.Y.Z-portable.zip`, the wheel, the sdist and `SHA256SUMS.txt`, its text the
    changelog's entry. PyPI follows, in a job of its own, only when the repository's variable
    `PUBLISH_TO_PYPI` is `true` (the owner has set up trusted publishing), so that PyPI not
    set up never holds the release back.
18. **The version written.** The first release is 0.1.0: in the files' names, the version
    resources of `Kresorter.exe` and of the installer, the Settings page (0015 item 4), the
    release's title, and the changelog's heading, dated the day of the tag.

## The licence (request 6)

19. **MIT, kept.** The licence stays the MIT licence, the owner's: `LICENSE` and
    `pyproject.toml` as they are.
20. **Shown.** The installer shows `LICENSE` before it installs (Inno Setup's `LicenseFile`);
    the Settings page says, under the version, that Kresorter is under the MIT licence and
    that the Windows build carries Qt and PySide6 under the LGPL-3.0; the README's License
    section says the same, in both languages.

## Docs

21. **The README** says the answers' language, LM Studio (its settings, its steps, what is
    sent), the release's files and the licence.
22. **The changelog** of 0.1.0 says the same, for its users.
23. **The roadmap** records this decision's work and its accepted limitations.

## The meta-test

24. **Every item of this decision is cited by a test** as `[0019.N]`. A meta-test fails on an
    item no test cites, on a citation of an item that does not exist, and on an item still
    listed as pending although a test cites it; the pending list starts with every item and is
    empty after the last commit of this decision's plan. The meta-test checks the rules of
    `tests/support/decisions.py` on made-up items and citations, and that check cites this
    item.

## Plan

Each line is one commit or one test/fix pair (red, then green). The items in brackets leave
the pending list in that commit, and no earlier test cites them.

1. This decision and its meta-test, every other item pending [24].
2. The answers' language; the thinking dropped [1, 2].
3. The icon [3, 4].
4. LM Studio in `llm`: the settings, the requests, the checks [5-9, 14].
5. LM Studio on the console [10, 11].
6. LM Studio in the window [12, 13].
7. The licence shown [19, 20].
8. The release [17, 18].
9. The README in Russian [15, 16].
10. The README, the changelog, the roadmap [21-23].

## Accepted limitations

- **A small model may still answer in another language**: the instruction asks; the answer is
  advisory and says it may be wrong.
- **LM Studio's first model is a guess** when none is chosen: an embedding model whose id does
  not say `embed` is taken, and its answer is refused as `http_status` or `bad_response`.
- **LM Studio says no version**: its line says only that it runs.
- **The executable is not signed**: Windows SmartScreen may warn the first time; signing needs
  a code-signing certificate, which the project does not have.

## The owner's answers

- The six requests; how each is done is this decision's (2026-11-04).
