"""The guard refuses writes by CONTENT_KEYS; redact-refused must blank the same keys, or a refused
search_and_replace body would be published in docs/bob-runs/ (security review, 2026-10-19)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _content_keys(path):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        names = [getattr(t, "id", None) for t in getattr(node, "targets", [])]
        if isinstance(node, ast.Assign) and "CONTENT_KEYS" in names:
            return set(ast.literal_eval(node.value))
    raise AssertionError(f"no CONTENT_KEYS in {path}")


def test_redact_blanks_every_key_the_guard_checks():
    guard = _content_keys(ROOT / ".bob" / "hooks" / "tool_guard.py")
    redact = _content_keys(ROOT / "scripts" / "redact-refused.py")
    assert guard <= redact, sorted(guard - redact)
