"""Failure isolation and reporting for dry-run-first maintenance commands."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from rich.console import Console
from rich.table import Column, Table


def fan_out[K, V](
    keys: Iterable[K], work: Callable[[K], V]
) -> tuple[list[tuple[K, V]], list[tuple[K, Exception]]]:
    """Run all planned targets, retaining each target's success or failure."""
    results: list[tuple[K, V]] = []
    failures: list[tuple[K, Exception]] = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(work, key): key for key in keys}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results.append((key, future.result()))
            except Exception as exc:
                failures.append((key, exc))
    return results, failures


def render_table(
    console: Console, columns: list[Column | str], rows: Iterable[tuple[str, ...]]
) -> None:
    table = Table(*columns)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def print_errors(
    console: Console, errors: Iterable[str], *, level: Literal["Warning", "Error"] = "Error"
) -> None:
    color = "yellow" if level == "Warning" else "red"
    for error in errors:
        console.print(f"[{color}]{level}:[/{color}] {error}")
