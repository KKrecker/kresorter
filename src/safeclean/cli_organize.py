"""``safeclean organize``'s messages (decision 0012, items 31 and 33-36).

What recovery found in organize's journal, as ``safeclean recover`` shows it: each batch it
closed with its state, the files still sorted, and the command that moves them back; an undo
batch that stopped names the batch it undoes, whose undo takes what is left.
"""

from __future__ import annotations

from typing import TextIO

from safeclean.organize.journal import BatchKind, BatchState
from safeclean.organize.recovery import RecoveredBatch, RecoveryReport
from safeclean.text import count

UNDO = "safeclean organize undo"


def report_recovery(report: RecoveryReport, out: TextIO, err: TextIO) -> bool:
    """Show what the recovery found, warnings on ``err``; was there anything?"""
    if report.batches:
        batches = len(report.batches)
        noun = "batch" if batches == 1 else "batches"
        lines = [f"Recovered {batches} interrupted organize {noun}:"]
        for batch in report.batches:
            lines += _recovered(batch)
        out.write("\n".join(lines) + "\n")
    for warning in report.warnings:
        err.write(f"safeclean: {warning}\n")
    return bool(report.batches)


def _recovered(batch: RecoveredBatch) -> list[str]:
    line = f"  [{batch.batch_id}] {batch.state}"
    if batch.kind is BatchKind.UNDO:
        if batch.state is not BatchState.DONE:
            line += f": the undo of batch {batch.undoing} stopped;"
            line += f" '{UNDO} {batch.undoing}' moves back the files still sorted"
        return [line]
    if batch.left:
        them = "it" if len(batch.left) == 1 else "them"
        line += f": {count(len(batch.left), 'file')} still sorted;"
        line += f" '{UNDO} {batch.batch_id}' moves {them} back"
    return [line, *(f"    {path}" for path in batch.left)]
