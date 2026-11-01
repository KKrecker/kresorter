r"""Disabling and enabling ``HKCU`` Run values by their ``StartupApproved`` flag (0011, 81-92).

The ``Run`` value itself is never written; its flag in ``Explorer\StartupApproved\Run`` is,
with the bytes the Task Manager writes: ``03 00 00 00`` and the FILETIME of the change to
disable, ``02`` and eleven zeros to enable. A missing flag means enabled; enabling never deletes
a value, it writes ``02``. The value must still be exactly as listed and is found again by its
digest; each change is journaled before the registry is written, and a failure is rolled back
only if the flag is as it was. Only ``HKCU`` Run values change; nothing can write ``HKLM``.
``recover()`` closes pending rows by the flag found there; it only reads the registry.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

from safeclean.autostart.changes import (
    Change,
    ChangeRecovery,
    ChangeRefusal,
    ChangeResult,
    ChangeState,
    finish_change,
    insert_change,
    refused,
)
from safeclean.autostart.models import AutostartItem, Scope, Source
from safeclean.autostart.registry import (
    Hive,
    RegistryError,
    RegValue,
    UserRegistry,
    ValueKind,
    value_digest,
)
from safeclean.autostart.run_keys import APPROVED, RUN, read_run_keys
from safeclean.storage.pending import has_pending
from safeclean.storage.transactions import transaction

ENABLED_FLAG = b"\x02" + bytes(11)
_DISABLED = b"\x03\x00\x00\x00"
_UNIX_EPOCH_AS_FILETIME = 116_444_736_000_000_000  # 1970-01-01 in 100 ns since 1601-01-01
_FLAGS = rf"{Hive.HKCU}\{APPROVED}" + "\\"  # a journaled location is this and the exact name
_NOT_WRITTEN = "interrupted before the registry was written"
_NEITHER = "the flag is neither as before nor as after the change"


class RunKeyChanges:
    def __init__(
        self,
        conn: sqlite3.Connection,
        registry: UserRegistry,
        *,
        now: Callable[[], int] = time.time_ns,
    ) -> None:
        self._conn = conn
        self._registry = registry
        self._now = now

    def disable(self, item: AutostartItem) -> ChangeResult:
        return self._change(item, "disable")

    def enable(self, item: AutostartItem) -> ChangeResult:
        return self._change(item, "enable")

    def _change(self, item: AutostartItem, action: str) -> ChangeResult:
        if item.source is not Source.RUN_KEY or item.scope is not Scope.USER:
            return refused(ChangeRefusal.READ_ONLY, "only HKCU Run values can be changed")
        if has_pending(self._conn):
            detail = "the journal has unfinished work; run recover() first"
            return refused(ChangeRefusal.PENDING, detail)
        if item not in read_run_keys(self._registry, include_machine=False).items:
            return refused(ChangeRefusal.CHANGED, "the value changed since it was listed")
        if item.enabled is not (action == "disable"):
            return refused(ChangeRefusal.ALREADY, f"the value is already {action}d")
        found = self._find(item.digest)
        if found is None:
            return refused(ChangeRefusal.CHANGED, "the value changed since it was listed")
        name, before = found
        after = self._disabled_flag() if action == "disable" else ENABLED_FLAG
        location = rf"{Hive.HKCU}\{APPROVED}\{name}"  # exact: "" is not "(Default)"
        change = Change(action, item.source, item.location, location, item.digest, before, after)
        with transaction(self._conn):
            change_id = insert_change(self._conn, change)
        try:
            self._registry.set_user_value(APPROVED, RegValue(name, ValueKind.REG_BINARY, after))
        except BaseException as error:
            message = str(error) or type(error).__name__
            restored = self._flags().get(name.casefold()) == before
            state = ChangeState.ROLLED_BACK if restored else ChangeState.FAILED
            finish_change(self._conn, change_id, state, message)
            if not isinstance(error, RegistryError):
                raise
            return ChangeResult(change_id, state, None, message)
        finish_change(self._conn, change_id, ChangeState.DONE, None)
        return ChangeResult(change_id, ChangeState.DONE)

    def recover(self) -> ChangeRecovery:
        """Close pending ``run_key`` changes by the flag in the registry; never write it."""
        pending = self._conn.execute(
            "SELECT id, location, value_before, value_after FROM autostart_changes"
            " WHERE state = ? AND source = ? ORDER BY id",
            (ChangeState.PENDING.value, Source.RUN_KEY.value),
        ).fetchall()
        closed: dict[ChangeState, list[int]] = {
            ChangeState.DONE: [],
            ChangeState.ROLLED_BACK: [],
            ChangeState.FAILED: [],
        }
        for change_id, location, before, after in pending:
            found = self._flags().get(location.removeprefix(_FLAGS).casefold())
            if found == after:
                state, error = ChangeState.DONE, None
            elif found == before:
                state, error = ChangeState.ROLLED_BACK, _NOT_WRITTEN
            else:
                state, error = ChangeState.FAILED, _NEITHER
            finish_change(self._conn, change_id, state, error)
            closed[state].append(change_id)
        return ChangeRecovery(
            tuple(closed[ChangeState.DONE]),
            tuple(closed[ChangeState.ROLLED_BACK]),
            tuple(closed[ChangeState.FAILED]),
        )

    def _find(self, digest: str) -> tuple[str, bytes | None] | None:
        """The name and flag bytes of the Run value with this digest, read once more."""
        flags = {f.name.casefold(): f for f in self._registry.values(Hive.HKCU, APPROVED) or ()}
        for value in self._registry.values(Hive.HKCU, RUN) or ():
            flag = flags.get(value.name.casefold())
            if value_digest(value, flag) == digest:
                return value.name, _data(flag)
        return None

    def _flags(self) -> dict[str, bytes | None]:
        flags = self._registry.values(Hive.HKCU, APPROVED) or ()
        return {f.name.casefold(): _data(f) for f in flags}

    def _disabled_flag(self) -> bytes:
        filetime = self._now() // 100 + _UNIX_EPOCH_AS_FILETIME
        return _DISABLED + filetime.to_bytes(8, "little")


def _data(flag: RegValue | None) -> bytes | None:
    """The bytes of a flag; a listed flag is always binary (``approved_state``)."""
    return flag.data if flag is not None and isinstance(flag.data, bytes) else None
