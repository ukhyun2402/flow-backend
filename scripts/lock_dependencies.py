"""Record the installed runtime dependency closure, without editable/local paths."""

from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

seen = set()


def collect(name):
    name = canonicalize_name(name)
    if name in seen:
        return
    seen.add(name)
    for raw in metadata.requires(name) or []:
        requirement = Requirement(raw)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            collect(requirement.name)


collect("flowstudio")
root = Path(__file__).resolve().parents[1]
root.joinpath("requirements.lock").write_text(
    "\n".join(
        f"{name}=={metadata.version(name)}"
        for name in sorted(seen)
        if name != "flowstudio"
    )
    + "\n",
    encoding="utf-8",
)
print("Runtime dependencies locked; no local workspace paths included.")
