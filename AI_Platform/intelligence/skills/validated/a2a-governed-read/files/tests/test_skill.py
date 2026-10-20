#!/usr/bin/env python3
"""Structural checks for the a2a-governed-read skill.

Stdlib only. Reads SKILL.md from the directory above this test, verifies the
frontmatter name, and verifies the body documents both procedures. Prints PASS
and exits 0 on success; prints FAIL and exits 1 on any failure.
"""

import os
import re
import sys

SKILL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "SKILL.md"
)

EXPECTED_NAME = "a2a-governed-read"
REQUIRED_BODY_TOKENS = ("SendMessage", "search_approved")


def split_frontmatter(text):
    """Return (frontmatter_str, body_str); frontmatter may be empty."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[1:idx]), "\n".join(lines[idx + 1 :])
    return "", text


def frontmatter_name(frontmatter):
    """Extract the scalar value of the top-level `name:` key."""
    match = re.search(r"^name:[ \t]*(.+?)[ \t]*$", frontmatter, re.MULTILINE)
    return match.group(1).strip() if match else None


def main():
    if not os.path.isfile(SKILL_PATH):
        print("FAIL: SKILL.md not found at %s" % os.path.normpath(SKILL_PATH))
        return 1

    with open(SKILL_PATH, encoding="utf-8") as handle:
        text = handle.read()

    frontmatter, body = split_frontmatter(text)
    if not frontmatter:
        print("FAIL: SKILL.md has no YAML frontmatter block")
        return 1

    name = frontmatter_name(frontmatter)
    if name != EXPECTED_NAME:
        print("FAIL: frontmatter name is %r, expected %r" % (name, EXPECTED_NAME))
        return 1

    missing = [token for token in REQUIRED_BODY_TOKENS if token not in body]
    if missing:
        print("FAIL: body is missing required token(s): %s" % ", ".join(missing))
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
