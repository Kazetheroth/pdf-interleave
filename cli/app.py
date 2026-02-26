from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.pagerange import PageRangeError, build_page_sequence
from core.validate import ValidationError, validate_input_file, validate_no_duplicates, validate_output_path


class DependencyError(RuntimeError):
    """Raised when a required runtime dependency is missing."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf_interleave",
        description="Interleave pages from two PDF files with independent page ordering.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    merge_parser = subparsers.add_parser("merge", help="Merge two PDFs by alternating pages.")
    merge_parser.add_argument("-a", "--input-a", required=True, help="Input PDF A")
    merge_parser.add_argument("-b", "--input-b", required=True, help="Input PDF B")
    merge_parser.add_argument("-o", "--output", required=True, help="Output PDF path")

    merge_parser.add_argument(
        "--order-a",
        choices=["asc", "desc", "range", "list", "slice"],
        default="asc",
        help="Page ordering mode for PDF A (default: asc).",
    )
    merge_parser.add_argument(
        "--order-b",
        choices=["asc", "desc", "range", "list", "slice"],
        default="asc",
        help="Page ordering mode for PDF B (default: asc).",
    )
    merge_parser.add_argument("--pages-a", help="Page expression for A (required for range/list/slice).")
    merge_parser.add_argument("--pages-b", help="Page expression for B (required for range/list/slice).")

    merge_parser.add_argument(
        "--start",
        choices=["A", "B"],
        default="A",
        help="Which sequence starts the interleave (default: A).",
    )
    merge_parser.add_argument(
        "--policy",
        choices=["append", "truncate", "error"],
        default="append",
        help="Policy for unequal sequence lengths (default: append).",
    )
    merge_parser.add_argument("--strict", action="store_true", help="Reject duplicate page selections.")
    merge_parser.add_argument("--verbose", action="store_true", help="Print merge diagnostics.")

    return parser


def run_merge(args: argparse.Namespace) -> int:
    input_a = validate_input_file(args.input_a, label="A")
    input_b = validate_input_file(args.input_b, label="B")
    output = validate_output_path(args.output, input_paths=[input_a, input_b])

    try:
        from core.merge import MergeError, build_interleave_plan, load_reader, write_interleaved_pdf
    except ModuleNotFoundError as exc:
        if exc.name == "pypdf":
            raise DependencyError("Missing dependency 'pypdf'. Install it with: pip install pypdf") from exc
        raise

    try:
        reader_a = load_reader(input_a, label="A")
        reader_b = load_reader(input_b, label="B")

        pages_a = build_page_sequence(
            order=args.order_a,
            pages_expr=args.pages_a,
            total_pages=len(reader_a.pages),
            source_label="A",
        )
        pages_b = build_page_sequence(
            order=args.order_b,
            pages_expr=args.pages_b,
            total_pages=len(reader_b.pages),
            source_label="B",
        )

        if args.strict:
            validate_no_duplicates(pages_a.one_based, label="A")
            validate_no_duplicates(pages_b.one_based, label="B")

        plan = build_interleave_plan(
            pages_a.zero_based,
            pages_b.zero_based,
            start=args.start,
            policy=args.policy,
        )

        write_interleaved_pdf(
            reader_a=reader_a,
            reader_b=reader_b,
            plan=plan,
            output_path=output,
        )

        if args.verbose:
            _print_verbose_summary(
                input_a=input_a,
                input_b=input_b,
                output=output,
                total_a=len(reader_a.pages),
                total_b=len(reader_b.pages),
                selected_a=len(pages_a.zero_based),
                selected_b=len(pages_b.zero_based),
                output_pages=len(plan),
                start=args.start,
                policy=args.policy,
            )
        return 0
    except MergeError as exc:
        raise ValidationError(str(exc)) from exc


def _print_verbose_summary(
    *,
    input_a: Path,
    input_b: Path,
    output: Path,
    total_a: int,
    total_b: int,
    selected_a: int,
    selected_b: int,
    output_pages: int,
    start: str,
    policy: str,
) -> None:
    print(f"A: {input_a} ({total_a} total pages, {selected_a} selected)")
    print(f"B: {input_b} ({total_b} total pages, {selected_b} selected)")
    print(f"start={start} policy={policy}")
    print(f"Output: {output} ({output_pages} pages)")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "merge":
            return run_merge(args)
        parser.print_help()
        return 2
    except (FileNotFoundError, ValidationError, PageRangeError, DependencyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
