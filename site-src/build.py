"""Build the GitHub Pages site into docs/. Run: python3 site-src/build.py"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from site_order import ORDER

DOCS = os.environ.get("PROOFS_SITE_OUT") or os.path.join(os.path.dirname(HERE), "docs")
os.makedirs(DOCS, exist_ok=True)
open(os.path.join(DOCS, ".nojekyll"), "w").close()
for skill in ORDER:
    subprocess.run([sys.executable, os.path.join(HERE, "skillpage_gen.py"), skill], check=True, cwd=HERE)
subprocess.run([sys.executable, os.path.join(HERE, "index_gen.py")], check=True, cwd=HERE)
