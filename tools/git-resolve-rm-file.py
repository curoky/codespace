#!/usr/bin/env python3
# Copyright (c) 2018-2023 curoky(cccuroky@gmail.com).
#
# This file is part of dotbox.
# See https://github.com/curoky/dotbox for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
'''
generate script for git-mv-with-history
Usage:
$ gst | git-resolve-move-file.py
'''

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
        raise typer.Abort('read null from stdin!')

    output = tempfile.NamedTemporaryFile(delete=False)
    output.close()

    content = ['git-obliterate']
    for line in lines:
        res = re.search(r'deleted:\s+([\S]+)\s*', line)
        if res:
            content.append(res.group(1))
    typer.secho(output.name)
    Path(output.name).write_text(' '.join(content), encoding='utf8')


if __name__ == '__main__':
    app()
