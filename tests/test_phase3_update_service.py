from __future__ import annotations

from pathlib import Path
import subprocess

from services.update_service import pull_repo_update


def _cp(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_pull_repo_update_fails_when_not_git_repo(tmp_path: Path):
    result = pull_repo_update(repo_dir=tmp_path)

    assert result.ok is False
    assert result.changed is False
    assert "Kein Git-Repository" in result.detail


def test_pull_repo_update_handles_detached_head(monkeypatch, tmp_path: Path):
    (tmp_path / ".git").mkdir()

    responses = [
        _cp(stdout="git version 2.43.0\n"),
        _cp(stdout="true\n"),
        _cp(stdout="HEAD\n"),
    ]

    def fake_run(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = pull_repo_update(repo_dir=tmp_path)

    assert result.ok is False
    assert result.changed is False
    assert "Detached HEAD" in result.detail


def test_pull_repo_update_reports_pull_error(monkeypatch, tmp_path: Path):
    (tmp_path / ".git").mkdir()

    responses = [
        _cp(stdout="git version 2.43.0\n"),
        _cp(stdout="true\n"),
        _cp(stdout="main\n"),
        _cp(stdout="a1b2c3d\n"),
        _cp(returncode=1, stderr="fatal: Not possible to fast-forward, aborting."),
    ]

    def fake_run(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = pull_repo_update(repo_dir=tmp_path)

    assert result.ok is False
    assert result.changed is False
    assert "Pull fehlgeschlagen" in result.detail
    assert result.branch == "main"
    assert result.commit_before == "a1b2c3d"


def test_pull_repo_update_success_with_new_commit(monkeypatch, tmp_path: Path):
    (tmp_path / ".git").mkdir()

    responses = [
        _cp(stdout="git version 2.43.0\n"),
        _cp(stdout="true\n"),
        _cp(stdout="main\n"),
        _cp(stdout="a1b2c3d\n"),
        _cp(stdout="Updating a1b2c3d..f6e7d8c\n"),
        _cp(stdout="f6e7d8c\n"),
    ]

    def fake_run(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = pull_repo_update(repo_dir=tmp_path)

    assert result.ok is True
    assert result.changed is True
    assert result.branch == "main"
    assert result.commit_before == "a1b2c3d"
    assert result.commit_after == "f6e7d8c"
