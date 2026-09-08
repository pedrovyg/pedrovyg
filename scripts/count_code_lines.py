#!/usr/bin/env python3
"""Count cached SLOC across Pedro's public, owned, non-fork repositories."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


USERNAME = "pedrovyg"
GITHUB_API = "https://api.github.com"
CACHE_SCHEMA = 1
DEFAULT_CACHE = Path("profile/code-lines.json")
DEFAULT_WORK_DIR = Path(".build/code-lines")
EXCLUDED_DIRECTORIES = (
    ".gradle",
    ".idea",
    ".next",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "generated",
    "node_modules",
    "out",
    "profile",
    "target",
    "vendor",
    "venv",
)
EXCLUDED_EXTENSIONS = (
    "7z",
    "avi",
    "bmp",
    "eot",
    "gif",
    "gz",
    "ico",
    "jpeg",
    "jpg",
    "lock",
    "map",
    "md",
    "mov",
    "mp3",
    "mp4",
    "otf",
    "pdf",
    "png",
    "rst",
    "tar",
    "txt",
    "ttf",
    "wav",
    "webm",
    "webp",
    "woff",
    "woff2",
    "zip",
)
EXCLUDED_FILE_PATTERN = (
    r"(?:^|/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock)$"
    r"|\.min\.(?:css|js)$"
)


@dataclass(frozen=True)
class Repository:
    """The immutable metadata needed to cache and count one repository."""

    full_name: str
    default_branch: str
    pushed_at: str
    size: int


def github_request_json(url: str, token: str) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "pedrovyg-code-lines",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        body = error.read(512).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API returned HTTP {error.code} for {url}: {body}"
        ) from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"GitHub API returned invalid JSON for {url}") from error


def repository_from_api(item: object) -> Repository | None:
    """Return a supported repository or None for private/forked/non-owned data."""
    if not isinstance(item, Mapping):
        raise RuntimeError("GitHub returned an invalid repository entry")
    owner = item.get("owner")
    owner_login = owner.get("login") if isinstance(owner, Mapping) else None
    if item.get("private") is not False or item.get("fork") is not False:
        return None
    if not isinstance(owner_login, str) or owner_login.casefold() != USERNAME.casefold():
        return None

    full_name = item.get("full_name")
    default_branch = item.get("default_branch")
    pushed_at = item.get("pushed_at")
    size = item.get("size")
    if (
        not isinstance(full_name, str)
        or not full_name.startswith(f"{USERNAME}/")
        or not isinstance(default_branch, str)
        or not default_branch
        or not isinstance(pushed_at, str)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
    ):
        raise RuntimeError(f"Repository metadata is incomplete: {full_name!r}")
    return Repository(full_name, default_branch, pushed_at, size)


def list_repositories(token: str) -> tuple[Repository, ...]:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to calculate Code Lines")

    repositories: list[Repository] = []
    page = 1
    while True:
        payload = github_request_json(
            f"{GITHUB_API}/users/{USERNAME}/repos"
            f"?type=owner&sort=full_name&direction=asc&per_page=100&page={page}",
            token,
        )
        if not isinstance(payload, list):
            raise RuntimeError("GitHub returned an invalid repository collection")
        for item in payload:
            repository = repository_from_api(item)
            if repository is not None:
                repositories.append(repository)
        if len(payload) < 100:
            break
        page += 1

    repositories.sort(key=lambda repository: repository.full_name.casefold())
    return tuple(repositories)


def load_cache(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid Code Lines cache at {path}: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid Code Lines cache structure at {path}")
    if payload.get("schema") != CACHE_SCHEMA or payload.get("username") != USERNAME:
        return {}
    if not isinstance(payload.get("repositories"), Mapping):
        raise RuntimeError(f"Invalid Code Lines repository cache at {path}")
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RuntimeError(f"Invalid Code Lines total in cache at {path}")
    return payload


def cloc_version(cloc: str) -> str:
    try:
        result = subprocess.run(
            [cloc, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Unable to execute cloc: {error}") from error
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("cloc returned an empty version")
    return version


def parse_cloc_json(output: str, repository: str) -> int:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"cloc returned invalid JSON for {repository}") from error
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"cloc returned an invalid report for {repository}")
    summary = payload.get("SUM")
    if summary is None:
        return 0
    if not isinstance(summary, Mapping):
        raise RuntimeError(f"cloc returned an invalid SUM for {repository}")
    code = summary.get("code")
    if isinstance(code, bool) or not isinstance(code, int) or code < 0:
        raise RuntimeError(f"cloc returned an invalid code count for {repository}")
    return code


def reset_child_directory(path: Path, parent: Path) -> None:
    resolved_parent = parent.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_parent or resolved_parent not in resolved_path.parents:
        raise RuntimeError(f"Refusing to reset unsafe repository path: {resolved_path}")
    if resolved_path.exists():
        shutil.rmtree(resolved_path)


def count_repository(repository: Repository, checkout: Path, cloc: str) -> int:
    reset_child_directory(checkout, checkout.parent)
    clone_url = f"https://github.com/{quote(repository.full_name, safe='/')}.git"
    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "--single-branch",
                "--branch",
                repository.default_branch,
                "--no-tags",
                "--quiet",
                clone_url,
                str(checkout),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        result = subprocess.run(
            [
                cloc,
                "--json",
                "--quiet",
                "--vcs=git",
                f"--exclude-dir={','.join(EXCLUDED_DIRECTORIES)}",
                f"--exclude-ext={','.join(EXCLUDED_EXTENSIONS)}",
                f"--not-match-f={EXCLUDED_FILE_PATTERN}",
            ],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()[-1200:]
        raise RuntimeError(
            f"Code Lines failed for {repository.full_name}: {detail}"
        ) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            f"Code Lines failed for {repository.full_name}: {error}"
        ) from error
    finally:
        if checkout.exists():
            shutil.rmtree(checkout)
    return parse_cloc_json(result.stdout, repository.full_name)


def cached_count(
    repository: Repository,
    cached_repositories: object,
    cached_cloc_version: object,
    current_cloc_version: str,
) -> int | None:
    if cached_cloc_version != current_cloc_version:
        return None
    if not isinstance(cached_repositories, Mapping):
        return None
    entry = cached_repositories.get(repository.full_name)
    if not isinstance(entry, Mapping):
        return None
    count = entry.get("code_lines")
    if (
        entry.get("default_branch") != repository.default_branch
        or entry.get("pushed_at") != repository.pushed_at
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
    ):
        return None
    return count


def write_cache(path: Path, payload: Mapping[str, object]) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def calculate_code_lines(
    repositories: Sequence[Repository],
    cache_path: Path,
    work_dir: Path,
    cloc: str = "cloc",
) -> int:
    cache = load_cache(cache_path)
    version = cloc_version(cloc)
    cached_repositories = cache.get("repositories")
    entries: dict[str, dict[str, object]] = {}

    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=work_dir) as temporary:
        temporary_root = Path(temporary)
        for index, repository in enumerate(repositories):
            count = cached_count(
                repository,
                cached_repositories,
                cache.get("cloc_version"),
                version,
            )
            if count is None:
                if repository.size == 0:
                    count = 0
                else:
                    print(f"Counting {repository.full_name}...", file=sys.stderr)
                    count = count_repository(
                        repository, temporary_root / f"repository-{index}", cloc
                    )
            entries[repository.full_name] = {
                "code_lines": count,
                "default_branch": repository.default_branch,
                "pushed_at": repository.pushed_at,
            }

    total = sum(int(entry["code_lines"]) for entry in entries.values())
    payload: dict[str, object] = {
        "cloc_version": version,
        "repositories": entries,
        "schema": CACHE_SCHEMA,
        "total": total,
        "username": USERNAME,
    }
    write_cache(cache_path, payload)
    return total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--cloc", default="cloc")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repositories = list_repositories(os.environ.get("GITHUB_TOKEN", ""))
    total = calculate_code_lines(
        repositories, args.cache, args.work_dir, cloc=args.cloc
    )
    print(total)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"Code Lines calculation failed: {error}") from error
