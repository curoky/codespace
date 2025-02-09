#!/usr/bin/env python3
"""
generate script for git-mv-with-history
Usage:
$ gst | git-resolve-move-file.py
"""

import re
import sys
import tempfile
from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def main():
    lines = sys.stdin.readlines()
    if not lines:
        raise typer.Abort("read null from stdin!")

    output = tempfile.NamedTemporaryFile(delete=False)
    output.close()

    content = ["git-obliterate"]
    for line in lines:
        res = re.search(r"deleted:\s+([\S]+)\s*", line)
        if res:
            content.append(res.group(1))
    typer.secho(output.name)
    Path(output.name).write_text(" ".join(content), encoding="utf8")


if __name__ == "__main__":
    app()
