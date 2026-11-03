"""Include shared Python contracts from the checkout or the unpacked sdist."""

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        shared = root / "shared"
        if not shared.is_dir():
            shared = root.parents[1] / "shared"
        if not (shared / "__init__.py").is_file():
            raise RuntimeError("The shared Python package is required to build FaultLine")
        # Include source files explicitly so caches and local artifacts cannot leak
        # into either artifact. In an sdist, these live alongside app/.
        for source in sorted(shared.rglob("*.py")):
            destination = Path("shared") / source.relative_to(shared)
            build_data["force_include"][str(source)] = destination.as_posix()
