import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "roadlog" / "dashboard" / "static"
SITE = ROOT / "site"
BANNER = '<div class="replay-banner">Recorded replay</div>'


def build(target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(STATIC, target / "static")
    for name in ("replay.js", "replay.css", "recording.json"):
        shutil.copy(SITE / name, target / name)
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    page = page.replace(
        '<script src="static/app.js"></script>',
        '<script src="replay.js"></script>\n  <script src="static/app.js"></script>',
    )
    stylesheet = '<link rel="stylesheet" href="static/style.css">'
    page = page.replace(stylesheet, f'{stylesheet}\n  <link rel="stylesheet" href="replay.css">')
    page = page.replace("<body>", f"<body>\n  {BANNER}")
    (target / "index.html").write_text(page, encoding="utf-8")
    (target / ".nojekyll").touch()
    return target


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site"))
