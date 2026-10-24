#!/usr/bin/env bash
# Run Home Assistant core's own checks against this integration.
#
# Clones core at HA_VERSION, copies the integration in with port_to_core.py
# and runs what core's CI runs for an integration: hassfest, requirements,
# ruff, codespell, prettier, yamllint, mypy (strict), pylint and pytest with
# coverage.
#
#   script/run_core_checks.sh [work-dir]
#
# Needs git, uv and (for prettier) node/npx. Quality scale rules that only
# the maintainer can complete (brands, dependency-transparency) are marked
# done in the throwaway checkout so the remaining rules can be validated;
# they stay "todo" in docs/core/quality_scale.yaml until they are true.
set -euo pipefail

HA_VERSION="${HA_VERSION:-2026.10.2}"  # set PLATFORMS=sensor to check the first, single-platform PR
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:-$(mktemp -d)}"
CORE="$WORK/core"
VENV="$WORK/venv"
COMPONENT="homeassistant/components/smart_monitor"
TESTS="tests/components/smart_monitor"

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

if [ ! -d "$CORE" ]; then
  step "Cloning Home Assistant core $HA_VERSION"
  git clone --quiet --depth 1 --branch "$HA_VERSION" https://github.com/home-assistant/core.git "$CORE"
fi
if [ ! -d "$VENV" ]; then
  step "Creating environment"
  uv venv --quiet --python 3.14 "$VENV"
  uv pip install --quiet --python "$VENV/bin/python" \
    -e "$CORE" -r "$CORE/requirements.txt" -r "$CORE/requirements_test.txt" \
    -r "$CORE/requirements_test_pre_commit.txt" paho-mqtt aiohasupervisor "$ROOT/library"
fi
export PATH="$VENV/bin:$PATH"
cd "$CORE"
git checkout --quiet -- .
git clean --quiet -fd -- homeassistant/components tests/components

step "Copying the integration into core"
python "$ROOT/script/port_to_core.py" "$CORE" ${PLATFORMS:+--platforms $PLATFORMS}
sed -i 's/  brands: todo/  brands: done/; s/  dependency-transparency: todo/  dependency-transparency: done/' \
  "$COMPONENT/quality_scale.yaml"
python - <<'PY'
# Add the integration to .strict-typing, keeping the components sorted in place.
from pathlib import Path

path = Path(".strict-typing")
lines = path.read_text().splitlines()
entry = "homeassistant.components.smart_monitor.*"
if entry not in lines:
    components = sorted([line for line in lines if line.startswith("homeassistant.components.")] + [entry])
    first = next(i for i, line in enumerate(lines) if line.startswith("homeassistant.components."))
    rest = [line for line in lines if not line.startswith("homeassistant.components.")]
    path.write_text("\n".join(rest[:first] + components + rest[first:]) + "\n")
PY

step "hassfest"
python -m script.hassfest
python -m script.hassfest --integration-path "$COMPONENT"

step "gen_requirements_all"
python -m script.gen_requirements_all
python -m script.gen_requirements_all validate

step "ruff"
ruff check "$COMPONENT" "$TESTS"
ruff format --check "$COMPONENT" "$TESTS"

step "codespell"
codespell --ignore-words-list=aiport,astroid,checkin,currenty,hass,iif,incomfort,lookin,nam,NotIn \
  --skip="*.csv,*.json,*.ambr" --quiet-level=2 "$COMPONENT" "$TESTS"

step "yamllint"
yamllint -c .yamllint "$COMPONENT"

if command -v npx >/dev/null; then
  step "prettier"
  npx --yes -p prettier@3.6.2 -p prettier-plugin-sort-json@4.2.0 prettier --check \
    $(find "$COMPONENT" "$TESTS" \( -name '*.json' -o -name '*.yaml' \) -not -path '*/fixtures/*')
else
  step "prettier skipped: npx not found"
fi

step "mypy"
# Unrelated components may report missing optional dependencies; only errors
# in this integration count.
mypy "$COMPONENT" > "$WORK/mypy.txt" || true
grep "^$COMPONENT" "$WORK/mypy.txt" && exit 1
echo "No mypy errors in $COMPONENT"

step "pylint"
pylint --ignore-missing-annotations=y "$COMPONENT" "$TESTS"

step "pytest"
python -m script.translations develop --all > /dev/null
python -m pytest "$TESTS" -p no:cacheprovider --cov="homeassistant.components.smart_monitor" \
  --cov-report=term-missing --cov-fail-under=100

step "All core checks passed"
