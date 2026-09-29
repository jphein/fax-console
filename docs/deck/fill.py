#!/usr/bin/env python3
"""Fill placeholders from slots.json. Unfilled slots stay visible, so a half-filled render is honest.

    fill.py slots.json IN OUT

HTML: <span class="slot" data-slot="key">…</span> becomes the value, and
      <div class="shot slot" data-slot="key" aria-label="…">…</div> becomes an <img>.
Markdown / JS / anything else: {{key}} becomes the value.
Exit 0 always; prints which keys are still empty so the caller can decide.
"""
import html
import json
import pathlib
import re
import sys


def main():
    slots_path, src, out = sys.argv[1:4]
    values = json.loads(pathlib.Path(slots_path).read_text(encoding="utf-8"))["values"]
    text = pathlib.Path(src).read_text(encoding="utf-8")
    missing = set()

    def value(key):
        v = values.get(key)
        if v is None or v == "":
            missing.add(key)
            return None
        return str(v)

    if src.endswith(".html"):
        def span(m):
            v = value(m.group(1))
            if v is None:
                return m.group(0)
            return f'<span class="filled" data-slot="{m.group(1)}">{html.escape(v)}</span>'

        def shot(m):
            v = value(m.group(1))
            if v is None:
                return m.group(0)
            return f'<img class="shot" src="{html.escape(v)}" alt="{m.group(2)}">'

        text = re.sub(r'<span class="slot" data-slot="([\w.]+)">[^<]*</span>', span, text)
        text = re.sub(r'<div class="shot slot" data-slot="([\w.]+)" aria-label="([^"]*)">.*?</div>',
                      shot, text, flags=re.S)
    else:
        text = re.sub(r"\{\{([\w.]+)\}\}", lambda m: value(m.group(1)) or m.group(0), text)

    pathlib.Path(out).write_text(text, encoding="utf-8")
    left = ", ".join(sorted(missing))
    print(f"{src} -> {out}: {len(missing)} slot(s) unfilled" + (f": {left}" if left else ""))


if __name__ == "__main__":
    main()
