"""Generate translations/en.json from strings.json.

Home Assistant core builds translations itself. Custom integrations ship
resolved files, so this replaces ``[%key:...%]`` references with the strings
they point to, taken from the installed homeassistant package.

Run with ``python script/gen_translations.py``; pass ``--check`` in CI.
"""

import json
from pathlib import Path
import re
import sys
from typing import Any

import homeassistant

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / "smart_monitor"
REFERENCE = re.compile(r"\[%key:([a-z0-9_:]+)%\]")


def _lookup(tree: dict[str, Any], path: str) -> str:
    node: Any = tree
    for part in path.split("::"):
        node = node[part]
    if not isinstance(node, str):
        raise TypeError(f"{path} is not a string")
    return node


def _resolve(value: Any, roots: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve(item, roots) for key, item in value.items()}
    if isinstance(value, str):
        while match := REFERENCE.search(value):
            value = value.replace(match.group(0), _lookup(roots, match.group(1)))
        return value
    return value


def main() -> int:
    """Write or check the English translation."""
    common = json.loads(
        (Path(homeassistant.__file__).parent / "strings.json").read_text()
    )
    strings = json.loads((INTEGRATION / "strings.json").read_text())
    roots = {**common, "component": {"smart_monitor": strings}}
    rendered = json.dumps(_resolve(strings, roots), indent=2, ensure_ascii=False) + "\n"
    target = INTEGRATION / "translations" / "en.json"
    if "--check" in sys.argv:
        if target.read_text() != rendered:
            print("translations/en.json is out of date, run script/gen_translations.py")
            return 1
        return 0
    target.write_text(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
