from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.version import InvalidVersion, Version


PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"


def _read_requirements(input_path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for raw_line in input_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            raise ValueError("Nested requirement files are not supported by this resolver.")
        requirements.append(Requirement(line))
    return requirements


def _fetch_package_json(package_name: str) -> dict:
    url = PYPI_JSON_URL.format(package=package_name)
    try:
        with urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Failed to fetch {package_name} from PyPI: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to fetch {package_name} from PyPI: {exc.reason}") from exc


def _stable_versions_from_releases(releases: dict, requirement: Requirement) -> list[Version]:
    versions: list[Version] = []
    for version_text, files in releases.items():
        if not files:
            continue
        if not any(not bool(file_info.get("yanked", False)) for file_info in files):
            continue
        try:
            version = Version(version_text)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease:
            continue
        if requirement.specifier and not requirement.specifier.contains(version, prereleases=False):
            continue
        versions.append(version)
    versions.sort(reverse=True)
    return versions


def _format_requirement(requirement: Requirement, version: Version) -> str:
    name = requirement.name
    if requirement.extras:
        extras = ",".join(sorted(requirement.extras))
        name = f"{name}[{extras}]"
    out = f"{name}=={version}"
    if requirement.marker:
        out += f"; {requirement.marker}"
    return out


def resolve_second_latest(requirement: Requirement) -> str:
    payload = _fetch_package_json(requirement.name)
    releases = payload.get("releases", {})
    stable_versions = _stable_versions_from_releases(releases, requirement)
    if not stable_versions:
        raise RuntimeError(f"No stable versions found for requirement: {requirement}")
    selected = stable_versions[1] if len(stable_versions) > 1 else stable_versions[0]
    return _format_requirement(requirement, selected)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve requirements to the second latest stable version on PyPI.",
    )
    parser.add_argument("--input", default="requirements.in", help="Path to source requirements file")
    parser.add_argument("--output", default="requirements.txt", help="Path to resolved pinned output")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input requirements file not found: {input_path}")

    requirements = _read_requirements(input_path)
    resolved_lines = [resolve_second_latest(req) for req in requirements]

    output_path.write_text("\n".join(resolved_lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(resolved_lines)} resolved requirements to {output_path}")
    for line in resolved_lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
