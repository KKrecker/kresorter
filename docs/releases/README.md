# Release records

Before the tag `vX.Y.Z`, the owner installs that version's artifacts on clean machines and
records what was done and seen in `docs/releases/X.Y.Z.md` (decision 0015, item 28): a run on
Windows 10 and one on Windows 11, each with the installer and the portable zip, and one on an
Ubuntu LTS with pipx. The release job's first step, `python packaging/release.py check vX.Y.Z`,
fails without that file, or while a run or one of its lines is missing or empty, and names
every gap.

A run's heading names its system: `## Windows 10 ...`, `## Windows 11 ...` and
`## Ubuntu NN.NN LTS` (`24.04`, `22.04`, ...). Each line is `- **Label**: what was done and
seen`, and may go on in indented lines; anything else, notes or a `###` heading under a run,
is kept as it is. Copy the form, replace `X.Y.Z`, and fill each line:

```markdown
# Kresorter X.Y.Z on clean machines

## Windows 10

- **System**:
- **Installed**: `Kresorter-X.Y.Z-setup.exe`, then `Kresorter-X.Y.Z-portable.zip` unzipped:
- **The window on a screen**:
- **A scan**:
- **A file quarantined and restored**:
- **Each page**:
- **A folder sorted and its batch undone**:
- **The uninstall**:

## Windows 11

- **System**:
- **Installed**: `Kresorter-X.Y.Z-setup.exe`, then `Kresorter-X.Y.Z-portable.zip` unzipped:
- **The window on a screen**:
- **A scan**:
- **A file quarantined and restored**:
- **Each page**:
- **A folder sorted and its batch undone**:
- **The uninstall**:

## Ubuntu 24.04 LTS

- **System**:
- **Installed**: `pipx install "kresorter[ui]"`:
- **The window on a screen**:
- **A scan**:
- **A file quarantined and restored**:
- **Each page**:
- **A folder sorted and its batch undone**:
- **The uninstall**:
```

- **System**: the edition, the version and the build (`winver`), or `lsb_release -d`, and the
  screen's size and scale.
- **Installed**: what was run, and where it went.
- **The window on a screen**: it opened on a real screen, in which language and scheme.
- **A scan**: Scan now on the Overview, and what it found.
- **A file quarantined and restored**: a file moved to the quarantine from Findings, then put
  back from the Quarantine page, where it was.
- **Each page**: each of the six opened.
- **A folder sorted and its batch undone**: Sort on the Organize page, then its batch undone.
- **The uninstall**: Settings → Apps on Windows (the portable folder deleted),
  `pipx uninstall kresorter` on Ubuntu; the program gone, the data directory still there.
