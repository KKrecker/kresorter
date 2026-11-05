"""Timings of kresorter's scan on a Windows runner, written as annotations (temporary bench)."""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import struct
import sys
import time
from dataclasses import replace
from pathlib import Path

from kresorter.core.open_files import ShareModeChecker
from kresorter.core.scanner import scan
from kresorter.environment import default_context


def note(title: str, text: str) -> None:
    text = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::notice title={title}::{text}", flush=True)


class NeverOpen:
    def is_open(self, path: object) -> bool:
        return False


def make_tree(root: Path, dirs: int, files: int) -> None:
    for d in range(dirs):
        folder = root / f"d{d:04}"
        folder.mkdir(parents=True, exist_ok=True)
        for n in range(files):
            (folder / f"file{n:03}.txt").write_bytes(b"x" * (n % 7 + d % 5))


def raw_walk(root: Path) -> int:
    count = 0
    stack = [str(root)]
    while stack:
        with os.scandir(stack.pop()) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                else:
                    e.stat(follow_symlinks=False)
                    count += 1
    return count


def timed(label: str, function):
    start = time.perf_counter()
    result = function()
    return label, time.perf_counter() - start, result


def scans(root: Path, title: str, together: list[str] | None = None) -> None:
    context = default_context()
    assert isinstance(context.open_files, ShareModeChecker), context.open_files
    never = replace(context, open_files=NeverOpen())
    for label, run in [
        ("scandir only", lambda: raw_walk(root)),
        ("scan, no open check, no hash", lambda: scan([root], never, hash_duplicates=False).files_scanned),
        ("scan, share-mode check, no hash", lambda: scan([root], context, hash_duplicates=False).files_scanned),
        ("scan again, share-mode check, no hash", lambda: scan([root], context, hash_duplicates=False).files_scanned),
        ("scan, no open check, hash", lambda: scan([root], never).files_scanned),
    ]:
        _, seconds, result = timed(label, run)
        line = f"{label}: {seconds:.2f} s, {result} files"
        if together is None:
            note(title, line)
        else:
            together.append(line)
    if together is not None:
        note(title, "\n".join(together))


def profile(root: Path) -> str:
    context = default_context()
    profiler = cProfile.Profile()
    profiler.enable()
    scan([root], context, hash_duplicates=False)
    profiler.disable()
    out = io.StringIO()
    pstats.Stats(profiler, stream=out).sort_stats("tottime").print_stats(14)
    return "\n".join(line[:150] for line in out.getvalue().splitlines()[-24:])


# --- a raw MFT read, as WizTree does it -----------------------------------------------------------


def fixup(buf: bytearray, off: int, sector: int) -> None:
    usa_off, usa_cnt = struct.unpack_from("<HH", buf, off + 4)
    for i in range(1, usa_cnt):
        p = off + i * sector - 2
        q = off + usa_off + 2 * i
        buf[p : p + 2] = buf[q : q + 2]


def runs_of(buf: bytearray, at: int) -> list[tuple[int, int]]:
    runs, lcn = [], 0
    while buf[at]:
        header = buf[at]
        nlen, nofs = header & 0xF, header >> 4
        length = int.from_bytes(buf[at + 1 : at + 1 + nlen], "little")
        delta = int.from_bytes(buf[at + 1 + nlen : at + 1 + nlen + nofs], "little", signed=True)
        lcn += delta
        runs.append((lcn, length))
        at += 1 + nlen + nofs
    return runs


def mft(drive: str) -> tuple[str, dict[int, tuple[int, str]], dict[int, int], int]:
    start = time.perf_counter()
    with open(rf"\\.\{drive}", "rb", buffering=0) as volume:
        boot = volume.read(512)
        sector = struct.unpack_from("<H", boot, 0x0B)[0]
        cluster = sector * boot[0x0D]
        mft_lcn = struct.unpack_from("<q", boot, 0x30)[0]
        per = struct.unpack_from("<b", boot, 0x40)[0]
        size = cluster * per if per > 0 else 1 << -per
        volume.seek(mft_lcn * cluster)
        first = bytearray(volume.read(max(size, sector)))
        fixup(first, 0, sector)
        at = struct.unpack_from("<H", first, 0x14)[0]
        runs = []
        while True:
            kind, length = struct.unpack_from("<II", first, at)
            if kind == 0xFFFFFFFF:
                break
            if kind == 0x80 and first[at + 8]:
                runs = runs_of(first, at + struct.unpack_from("<H", first, at + 0x20)[0])
                break
            at += length
        names: dict[int, tuple[int, str]] = {}
        sizes: dict[int, int] = {}
        records = 0
        number = 0
        read_seconds = 0.0
        H = struct.Struct("<H").unpack_from
        I2 = struct.Struct("<II").unpack_from
        Q = struct.Struct("<Q").unpack_from
        chunk = 64 << 20
        for lcn, length in runs:
            offset, left = lcn * cluster, length * cluster
            while left:
                take = min(left, chunk)
                t = time.perf_counter()
                volume.seek(offset)
                buf = bytearray(volume.read(take))
                read_seconds += time.perf_counter() - t
                offset += take
                left -= take
                for off in range(0, len(buf), size):
                    n = number
                    number += 1
                    if buf[off : off + 4] != b"FILE" or not buf[off + 0x16] & 1:
                        continue
                    records += 1
                    fixup(buf, off, sector)
                    base = Q(buf, off + 0x20)[0] & 0xFFFFFFFFFFFF
                    owner = base or n
                    at = off + H(buf, off + 0x14)[0]
                    end = off + size
                    while at < end:
                        kind, length = I2(buf, at)
                        if kind == 0xFFFFFFFF or length == 0:
                            break
                        if kind == 0x30:
                            v = at + H(buf, at + 0x14)[0]
                            space = buf[v + 0x41]
                            if space != 2:
                                count = buf[v + 0x40]
                                parent = Q(buf, v)[0] & 0xFFFFFFFFFFFF
                                names[owner] = (parent, buf[v + 0x42 : v + 0x42 + 2 * count].decode("utf-16-le"))
                        elif kind == 0x80 and buf[at + 9] == 0:
                            if buf[at + 8]:
                                sizes[owner] = Q(buf, at + 0x30)[0]
                            else:
                                sizes[owner] = I2(buf, at + 0x10)[0]
                        at += length
    seconds = time.perf_counter() - start
    return f"{records} records in {seconds:.2f} s (reading {read_seconds:.2f} s), record {size} B, {len(runs)} runs", names, sizes, records


def paths_under(names: dict[int, tuple[int, str]], drive: str, root: Path) -> tuple[int, float]:
    start = time.perf_counter()
    cache: dict[int, str] = {5: drive + "\\"}

    def path(n: int, depth: int = 0) -> str:
        found = cache.get(n)
        if found is not None:
            return found
        parent, name = names.get(n, (5, f"?{n}"))
        if depth > 200 or parent == n:
            return "?"
        made = os.path.join(path(parent, depth + 1), name)
        cache[n] = made
        return made

    prefix = str(root).lower() + "\\"
    count = sum(1 for n in names if path(n).lower().startswith(prefix))
    return count, time.perf_counter() - start


def main() -> None:
    synthetic = Path(os.environ["RUNNER_TEMP"]) / "bench"
    t = time.perf_counter()
    make_tree(synthetic, 400, 100)
    made = f"40000 files made in {time.perf_counter() - t:.1f} s on {synthetic}"
    scans(synthetic, "synthetic", [made])
    real = Path(sys.argv[1])
    drive = real.drive or "C:"
    try:
        summary, names, sizes, records = mft(drive)
        count, seconds = paths_under(names, drive, real)
        note(f"MFT {drive}", f"{summary}\nnames {len(names)}, sizes {len(sizes)}\npaths built and {count} under {real} in {seconds:.2f} s")
    except Exception as error:  # the bench reports, never stops
        note(f"MFT {drive} failed", repr(error))
    note("profile, real, share-mode", profile(real))
    scans(real, f"real {real}")


if __name__ == "__main__":
    main()
