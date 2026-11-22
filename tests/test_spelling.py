"""Proofs' own shipped text stays in American English, whatever PROOFS_SPELLING says."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "review_page"))
import review_page  # noqa: E402

MARKER = "british-ok"


class Shipped(unittest.TestCase):
    def files(self):
        for top in ("skills", "shared", "reference"):
            for p in sorted((ROOT / top).rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    yield p
        yield ROOT / "README.md"
        yield ROOT / "evals" / "README.md"

    def test_shipped_text_is_american(self):
        table = ROOT / "shared" / "review_page" / "review_page.py"
        found = []
        for p in self.files():
            try:
                lines = p.read_text().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            in_table = False
            for n, line in enumerate(lines, 1):
                if p == table:
                    if line.startswith("BRITISH = {"):
                        in_table = True
                    if in_table:
                        in_table = line.strip() != "}"
                        continue
                if MARKER in line:
                    continue
                for rx, _stem, us in review_page._BRITISH_RE:
                    m = rx.search(line)
                    if m:
                        found.append("%s:%d %r (American: %s)" % (p.relative_to(ROOT), n, m.group(0), us))
        self.assertEqual(found, [], "British spelling in shipped text:\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
