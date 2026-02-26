from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter


class MergeError(ValueError):
    """Raised when merge planning or execution fails."""


@dataclass(frozen=True)
class MergePlanItem:
    source: str
    page_index: int


def load_reader(path: Path, *, label: str) -> PdfReader:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        raise MergeError(f"{label}: failed to read PDF '{path}': {exc}") from exc
    if getattr(reader, "is_encrypted", False):
        raise MergeError(f"{label}: encrypted PDFs are not supported.")
    return reader


def build_interleave_plan(
    seq_a: list[int],
    seq_b: list[int],
    *,
    start: str,
    policy: str,
) -> list[MergePlanItem]:
    start = start.upper()
    policy = policy.lower()
    if start not in {"A", "B"}:
        raise MergeError("Invalid --start value. Use A or B.")
    if policy not in {"append", "truncate", "error"}:
        raise MergeError("Invalid --policy value. Use append, truncate, or error.")
    if policy == "error" and len(seq_a) != len(seq_b):
        raise MergeError(
            "Size mismatch: sequence lengths differ "
            f"(A={len(seq_a)}, B={len(seq_b)}) and --policy=error."
        )

    queue_a = deque(seq_a)
    queue_b = deque(seq_b)
    plan: list[MergePlanItem] = []
    next_source = start

    while queue_a and queue_b:
        if next_source == "A":
            plan.append(MergePlanItem(source="A", page_index=queue_a.popleft()))
            next_source = "B"
        else:
            plan.append(MergePlanItem(source="B", page_index=queue_b.popleft()))
            next_source = "A"

    if policy == "append":
        while queue_a:
            plan.append(MergePlanItem(source="A", page_index=queue_a.popleft()))
        while queue_b:
            plan.append(MergePlanItem(source="B", page_index=queue_b.popleft()))
    elif policy == "error" and (queue_a or queue_b):
        # Defensive path if called with precomputed subsequences.
        raise MergeError(
            "Size mismatch: sequence lengths differ and --policy=error."
        )

    return plan


def write_interleaved_pdf(
    *,
    reader_a: PdfReader,
    reader_b: PdfReader,
    plan: list[MergePlanItem],
    output_path: Path,
) -> None:
    writer = PdfWriter()
    for item in plan:
        if item.source == "A":
            writer.add_page(reader_a.pages[item.page_index])
        else:
            writer.add_page(reader_b.pages[item.page_index])

    with output_path.open("wb") as output_file:
        writer.write(output_file)
