"""Shared fan-out and terminal rendering for maintenance commands."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.table import Table


def fan_out[K, V](
    keys: Iterable[K],
    work: Callable[[K], V],
) -> tuple[list[tuple[K, V]], list[tuple[K, Exception]]]:
    """Run ``work(key)`` for every key concurrently, isolating per-key failures.

    Returns successful ``(key, value)`` pairs plus the ``(key, exception)`` pairs
    whose work raised, so callers format their own error labels.
    """
    results: list[tuple[K, V]] = []
    failures: list[tuple[K, Exception]] = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(work, key): key for key in keys}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results.append((key, future.result()))
            except Exception as exc:  # a per-key failure surfaces in the report
                failures.append((key, exc))
    return results, failures


def render_table(
    console: Console,
    columns: list[dict[str, object]],
    rows: Iterable[tuple[str, ...]],
) -> None:
    """Print a table from ``add_column`` keyword specs and row tuples."""
    table = Table()
    for column in columns:
        table.add_column(**column)  # type: ignore[arg-type]
    for row in rows:
        table.add_row(*row)
    console.print(table)


def print_warnings(console: Console, warnings: Iterable[str]) -> None:
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def print_errors(console: Console, errors: Iterable[str]) -> None:
    for error in errors:
        console.print(f"[red]Error:[/red] {error}")
