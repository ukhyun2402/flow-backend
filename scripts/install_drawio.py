"""Install the official draw.io release locally; preserve its license and version."""

import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
TOOLS.mkdir(exist_ok=True)
VERSION = "v32.4.1"
SHA256 = "b83663313ccdecef6581476a7eaa96750bccf1bfdc3768981eb5d95e94be7820"
asset_url = f"https://github.com/jgraph/drawio/releases/download/{VERSION}/draw.war"
target = TOOLS / "draw.war"
if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != SHA256:
    urllib.request.urlretrieve(asset_url, target)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
if digest != SHA256:
    raise RuntimeError("Official draw.io asset digest mismatch")
output = TOOLS / "drawio"
output.mkdir(exist_ok=True)
with zipfile.ZipFile(target) as archive:
    if sum(f.file_size for f in archive.infolist()) > 800_000_000:
        raise RuntimeError("Unexpected draw.io unpacked size")
    for item in archive.infolist():
        path = (output / item.filename).resolve()
        if not path.is_relative_to(output.resolve()):
            raise RuntimeError("Archive path escapes installation directory")
        if item.filename.startswith(
            ("WEB-INF/", "META-INF/")
        ) or item.filename.endswith(".jsp"):
            continue
        archive.extract(item, output)
(TOOLS / "drawio-version.json").write_text(
    json.dumps(
        {
            "version": VERSION,
            "sha256": digest,
            "source": asset_url,
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(f"draw.io {VERSION} installed locally; sha256={digest}")
