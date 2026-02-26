from __future__ import annotations

from pathlib import Path


class ValidationError(ValueError):
    """Raised when input data fails validation."""


def validate_input_file(path: str, *, label: str) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"{label}: file not found: {candidate}")
    if not candidate.is_file():
        raise ValidationError(f"{label}: not a file: {candidate}")
    return candidate


def validate_output_path(path: str, *, input_paths: list[Path]) -> Path:
    output = Path(path)
    parent = output.parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

    output_resolved = output.resolve()
    input_resolved = {input_path.resolve() for input_path in input_paths}
    if output_resolved in input_resolved:
        raise ValidationError("Output path must be different from both input files.")

    return output


def validate_no_duplicates(pages: list[int], *, label: str) -> None:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for page in pages:
        if page in seen:
            duplicates.add(page)
        seen.add(page)
    if duplicates:
        duplicate_list = ", ".join(str(page) for page in sorted(duplicates))
        raise ValidationError(f"{label}: duplicate pages detected: {duplicate_list}")
