from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(slots=True)
class RepoUpdateResult:
    ok: bool
    changed: bool
    detail: str
    branch: str | None = None
    commit_before: str | None = None
    commit_after: str | None = None


def _summarize_process_output(*, stdout: str, stderr: str, max_len: int = 240) -> str:
    text = (stdout or "").strip() or (stderr or "").strip()
    compact = " ".join(text.split())
    if not compact:
        return "no output"
    if len(compact) <= max_len:
        return compact
    return f"{compact[: max_len - 3]}..."


def _run_git(repo_dir: Path, *args: str, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=False,
        timeout=max(5, int(timeout_seconds)),
    )


def pull_repo_update(*, repo_dir: Path | str | None = None, timeout_seconds: int = 45) -> RepoUpdateResult:
    root = Path(repo_dir or Path.cwd()).resolve()
    git_metadata = root / ".git"
    if not git_metadata.exists():
        return RepoUpdateResult(
            ok=False,
            changed=False,
            detail=f"Kein Git-Repository gefunden unter `{root}`.",
        )

    try:
        version_cp = _run_git(root, "--version", timeout_seconds=timeout_seconds)
    except FileNotFoundError:
        return RepoUpdateResult(ok=False, changed=False, detail="`git` ist auf dem Host nicht installiert.")
    except subprocess.TimeoutExpired:
        return RepoUpdateResult(ok=False, changed=False, detail="`git --version` Timeout.")
    if version_cp.returncode != 0:
        return RepoUpdateResult(
            ok=False,
            changed=False,
            detail=f"`git` nicht nutzbar: {_summarize_process_output(stdout=version_cp.stdout, stderr=version_cp.stderr)}",
        )

    try:
        inside_cp = _run_git(root, "rev-parse", "--is-inside-work-tree", timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        return RepoUpdateResult(ok=False, changed=False, detail="Git-Worktree-Pruefung Timeout.")
    if inside_cp.returncode != 0 or (inside_cp.stdout or "").strip().lower() != "true":
        return RepoUpdateResult(
            ok=False,
            changed=False,
            detail=(
                "Pfad ist kein gueltiger Git-Worktree: "
                f"{_summarize_process_output(stdout=inside_cp.stdout, stderr=inside_cp.stderr)}"
            ),
        )

    branch_cp = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout_seconds=timeout_seconds)
    branch = (branch_cp.stdout or "").strip() if branch_cp.returncode == 0 else None
    if branch in {None, "", "HEAD"}:
        return RepoUpdateResult(
            ok=False,
            changed=False,
            detail=(
                "Detached HEAD erkannt. `git pull` ist in diesem Zustand nicht moeglich "
                "(typisch in GitHub Actions Checkout ohne Branch)."
            ),
            branch=branch,
        )

    before_cp = _run_git(root, "rev-parse", "--short", "HEAD", timeout_seconds=timeout_seconds)
    before = (before_cp.stdout or "").strip() if before_cp.returncode == 0 else None

    try:
        pull_cp = _run_git(
            root,
            "-c",
            "pull.rebase=false",
            "pull",
            "--ff-only",
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return RepoUpdateResult(
            ok=False,
            changed=False,
            detail="`git pull --ff-only` Timeout.",
            branch=branch,
            commit_before=before,
        )

    if pull_cp.returncode != 0:
        return RepoUpdateResult(
            ok=False,
            changed=False,
            detail=f"Pull fehlgeschlagen: {_summarize_process_output(stdout=pull_cp.stdout, stderr=pull_cp.stderr)}",
            branch=branch,
            commit_before=before,
        )

    after_cp = _run_git(root, "rev-parse", "--short", "HEAD", timeout_seconds=timeout_seconds)
    after = (after_cp.stdout or "").strip() if after_cp.returncode == 0 else before
    changed = bool(before and after and before != after)

    if changed:
        detail = f"Update erfolgreich auf Branch `{branch}`: `{before}` -> `{after}`."
    else:
        detail = (
            f"Repository auf Branch `{branch}` bereits aktuell ({after or before or 'unknown'}). "
            f"{_summarize_process_output(stdout=pull_cp.stdout, stderr=pull_cp.stderr)}"
        )

    return RepoUpdateResult(
        ok=True,
        changed=changed,
        detail=detail,
        branch=branch,
        commit_before=before,
        commit_after=after,
    )
