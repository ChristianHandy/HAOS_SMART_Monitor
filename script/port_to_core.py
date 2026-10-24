"""Copy the integration and its tests into a Home Assistant core checkout.

Usage: python script/port_to_core.py /path/to/home-assistant/core [--platforms sensor]

New core integrations may only add one platform in their first pull request;
use ``--platforms`` to drop the others from the copy.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "custom_components" / "smart_monitor"
TESTS = ROOT / "tests"
DOMAIN = "smart_monitor"
ALL_PLATFORMS = ("binary_sensor", "button", "sensor")

_IMPORT_REWRITES = (
    ("pytest_homeassistant_custom_component.common", "tests.common"),
    ("pytest_homeassistant_custom_component.components", "tests.components"),
    ("pytest_homeassistant_custom_component.typing", "tests.typing"),
    ("custom_components.smart_monitor", "homeassistant.components.smart_monitor"),
)
_CUSTOM_ONLY = re.compile(r"# BEGIN CUSTOM-ONLY.*?# END CUSTOM-ONLY\n\n*", re.DOTALL)


def _rewrite_python(text: str) -> str:
    text = _CUSTOM_ONLY.sub("", text)
    for old, new in _IMPORT_REWRITES:
        text = text.replace(old, new)
    return text


def _dump_json(data: object) -> str:
    """Format JSON the way prettier does: short arrays stay on one line."""
    text = json.dumps(data, indent=2, ensure_ascii=False)

    def _collapse(match: re.Match[str]) -> str:
        items = [item.strip() for item in match.group(2).split(",\n")]
        line = f"{match.group(1)}[{', '.join(items)}]"
        return line if len(line) <= 80 else match.group(0)

    return (
        re.sub(
            r"(^ *\"[^\"]+\": )\[\n((?: *\"[^\"\n]*\",?\n)+) *\]",
            _collapse,
            text,
            flags=re.MULTILINE,
        )
        + "\n"
    )


def _drop_platforms(text: str, removed: set[str]) -> str:
    for platform in removed:
        text = text.replace(f"Platform.{platform.upper()}, ", "")
        text = text.replace(f", Platform.{platform.upper()}", "")
    return text


def main() -> None:
    """Copy the integration."""
    parser = argparse.ArgumentParser()
    parser.add_argument("core", type=Path)
    parser.add_argument("--platforms", nargs="+", default=list(ALL_PLATFORMS))
    args = parser.parse_args()
    removed = set(ALL_PLATFORMS) - set(args.platforms)

    target = args.core / "homeassistant" / "components" / DOMAIN
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for path in SOURCE.iterdir():
        if path.name in ("translations", "__pycache__") or path.stem in removed:
            continue
        if path.suffix == ".py":
            text = _drop_platforms(_rewrite_python(path.read_text()), removed)
            (target / path.name).write_text(text)
        elif path.name != "manifest.json":
            shutil.copy(path, target / path.name)

    manifest = json.loads((SOURCE / "manifest.json").read_text())
    for key in ("issue_tracker", "version"):
        manifest.pop(key)
    manifest["documentation"] = f"https://www.home-assistant.io/integrations/{DOMAIN}"
    manifest["quality_scale"] = "bronze"
    manifest = {"domain": manifest.pop("domain"), "name": manifest.pop("name")} | dict(
        sorted(manifest.items())
    )
    (target / "manifest.json").write_text(_dump_json(manifest))
    shutil.copy(ROOT / "docs" / "core" / "quality_scale.yaml", target)

    # Strings for platforms that are not part of this copy must go too.
    strings = json.loads((target / "strings.json").read_text())
    icons = json.loads((target / "icons.json").read_text())
    for platform in removed:
        strings["entity"].pop(platform, None)
        icons["entity"].pop(platform, None)
    if not strings["entity"]:
        strings.pop("entity")
    (target / "strings.json").write_text(_dump_json(strings))
    (target / "icons.json").write_text(_dump_json(icons))

    tests = args.core / "tests" / "components" / DOMAIN
    shutil.rmtree(tests, ignore_errors=True)
    tests.mkdir(parents=True)
    for path in TESTS.rglob("*"):
        relative = path.relative_to(TESTS)
        if (
            "__pycache__" in relative.parts
            or path.is_dir()
            or relative.name == "ruff.toml"
        ):
            continue
        if path.stem in {f"test_{platform}" for platform in removed}:
            continue
        destination = tests / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".py":
            destination.write_text(_rewrite_python(path.read_text()))
        else:
            shutil.copy(path, destination)

    # Imports sort differently once custom_components becomes homeassistant.
    ruff = shutil.which("ruff")
    if ruff:
        for command in (["check", "--fix", "--quiet"], ["format", "--quiet"]):
            subprocess.run(
                [ruff, *command, str(target), str(tests)], cwd=args.core, check=False
            )
    else:
        print("ruff not found; run 'ruff check --fix' and 'ruff format' in core")

    print(f"Copied to {target} and {tests}")
    if removed:
        print(f"Dropped platforms: {', '.join(sorted(removed))}")


if __name__ == "__main__":
    main()
