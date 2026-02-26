from __future__ import annotations

from dataclasses import dataclass


class PageRangeError(ValueError):
    """Raised when a page selection expression is invalid."""


@dataclass(frozen=True)
class ParsedPages:
    zero_based: list[int]
    one_based: list[int]


def build_page_sequence(
    *,
    order: str,
    pages_expr: str | None,
    total_pages: int,
    source_label: str,
) -> ParsedPages:
    if total_pages < 1:
        raise PageRangeError(f"{source_label}: PDF has no pages.")

    order = order.lower()
    if order not in {"asc", "desc", "range", "list", "slice"}:
        raise PageRangeError(f"{source_label}: Unsupported order mode '{order}'.")

    if order == "asc":
        pages = _asc_sequence(total_pages) if pages_expr is None else sorted(_parse_auto(pages_expr, total_pages))
    elif order == "desc":
        pages = _desc_sequence(total_pages) if pages_expr is None else sorted(
            _parse_auto(pages_expr, total_pages), reverse=True
        )
    elif order == "range":
        pages = _parse_range_required(pages_expr, source_label)
    elif order == "list":
        pages = _parse_list_required(pages_expr, source_label)
    else:
        pages = _parse_slice_required(pages_expr, total_pages, source_label)

    _validate_bounds(pages, total_pages=total_pages, source_label=source_label)
    return ParsedPages(
        zero_based=[page - 1 for page in pages],
        one_based=pages,
    )


def _asc_sequence(total_pages: int) -> list[int]:
    return list(range(1, total_pages + 1))


def _desc_sequence(total_pages: int) -> list[int]:
    return list(range(total_pages, 0, -1))


def _parse_auto(expr: str, total_pages: int) -> list[int]:
    expr = expr.strip()
    if not expr:
        raise PageRangeError("Empty page expression.")
    if "," in expr:
        return _parse_list(expr)
    if ":" in expr:
        return _parse_slice(expr, total_pages=total_pages)
    if "-" in expr:
        return _parse_range(expr)
    return [int(_parse_positive_number(expr, what="page number"))]


def _parse_range_required(expr: str | None, source_label: str) -> list[int]:
    if expr is None:
        raise PageRangeError(f"{source_label}: --pages value is required for order=range.")
    return _parse_range(expr)


def _parse_list_required(expr: str | None, source_label: str) -> list[int]:
    if expr is None:
        raise PageRangeError(f"{source_label}: --pages value is required for order=list.")
    return _parse_list(expr)


def _parse_slice_required(expr: str | None, total_pages: int, source_label: str) -> list[int]:
    if expr is None:
        raise PageRangeError(f"{source_label}: --pages value is required for order=slice.")
    return _parse_slice(expr, total_pages=total_pages)


def _parse_range(expr: str) -> list[int]:
    parts = expr.strip().split("-")
    if len(parts) != 2:
        raise PageRangeError(f"Invalid range syntax '{expr}'. Expected format like 5-20.")
    start = _parse_positive_number(parts[0], what="range start")
    end = _parse_positive_number(parts[1], what="range end")

    step = 1 if end >= start else -1
    return list(range(start, end + step, step))


def _parse_list(expr: str) -> list[int]:
    raw_parts = [p.strip() for p in expr.strip().split(",")]
    if not raw_parts or any(part == "" for part in raw_parts):
        raise PageRangeError(f"Invalid list syntax '{expr}'. Example: 1,3,2,10")
    return [_parse_positive_number(part, what="list item") for part in raw_parts]


def _parse_slice(expr: str, total_pages: int) -> list[int]:
    parts = expr.strip().split(":")
    if len(parts) not in {2, 3}:
        raise PageRangeError(f"Invalid slice syntax '{expr}'. Expected start:end:step.")

    start_raw = parts[0].strip() if len(parts) > 0 else ""
    end_raw = parts[1].strip() if len(parts) > 1 else ""
    step_raw = parts[2].strip() if len(parts) == 3 else ""

    try:
        step = int(step_raw) if step_raw else 1
    except ValueError as exc:
        raise PageRangeError(f"Invalid slice step: '{step_raw}'. Expected an integer.") from exc
    if step == 0:
        raise PageRangeError("Slice step cannot be 0.")

    if start_raw:
        start = _parse_positive_number(start_raw, what="slice start")
    else:
        start = 1 if step > 0 else total_pages
    if end_raw:
        end = _parse_positive_number(end_raw, what="slice end")
    else:
        end = total_pages if step > 0 else 1

    seq: list[int] = []
    if step > 0:
        current = start
        while current <= end:
            seq.append(current)
            current += step
    else:
        current = start
        while current >= end:
            seq.append(current)
            current += step
    if not seq:
        raise PageRangeError(f"Slice '{expr}' produced no pages.")
    return seq


def _parse_positive_number(value: str, *, what: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise PageRangeError(f"Invalid {what}: '{value}'. Expected an integer.") from exc
    if number < 1:
        raise PageRangeError(f"Invalid {what}: '{value}'. Must be >= 1.")
    return number


def _validate_bounds(pages: list[int], *, total_pages: int, source_label: str) -> None:
    for page in pages:
        if page < 1 or page > total_pages:
            raise PageRangeError(
                f"{source_label}: page {page} is out of bounds (valid range: 1-{total_pages})."
            )
