# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Release-policy regressions using synthetic archives and an in-memory API."""

import io
import json
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from http.client import HTTPMessage
from typing import Any

import pytest

from scripts import release_pipeline as release
from scripts import sync_version_from_tag

pytestmark = pytest.mark.unit
SHA = "a" * 40
REPOSITORY = "owner/StateMerger"
TAG = "v3.2.1"


@pytest.fixture
def release_bundle(tmp_path):
    root, dist = tmp_path / "root", tmp_path / "dist"
    root.mkdir()
    dist.mkdir()
    for name in release.FIXED_FILES - {"state-merger.exe"}:
        (root / name).write_text("synthetic release fixture\n")
    (dist / "state-merger.exe").write_bytes(b"synthetic executable")
    metadata = b"Metadata-Version: 2.4\nName: vic3-state-merger\nVersion: 3.2.1\n\n"
    with zipfile.ZipFile(
        dist / "vic3_state_merger-3.2.1-py3-none-any.whl", "w"
    ) as archive:
        prefix = "vic3_state_merger-3.2.1.dist-info"
        archive.writestr(f"{prefix}/METADATA", metadata)
        for name in ("state_traits", "flag_definitions_usa", "usa_state_counter"):
            archive.writestr(f"vic3_state_merger/assets/{name}.py", "# fixture")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            archive.writestr(f"{prefix}/licenses/{name}", "fixture")
    with tarfile.open(dist / "vic3_state_merger-3.2.1.tar.gz", "w:gz") as archive:
        for name, contents in (
            ("PKG-INFO", metadata),
            ("LICENSE", b"fixture"),
            ("THIRD_PARTY_NOTICES.md", b"fixture"),
        ):
            member = tarfile.TarInfo(f"vic3_state_merger-3.2.1/{name}")
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    target = tmp_path / "bundle"
    release.bundle(root, dist, target, TAG, SHA, REPOSITORY, "123")
    return target


class FakeGitHub:
    repository = REPOSITORY

    def __init__(self):
        self.sha = SHA
        self.annotated = False
        self.current: dict[str, Any] | None = None
        self.uploaded = []
        self.writes = []
        self.fail_upload: int | None = None
        self.expired = False

    def release(self, tag):
        return self.current

    def request(
        self, method: str, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        if method == "GET":
            if path == f"git/ref/tags/{TAG}":
                return {
                    "object": {
                        "type": "tag" if self.annotated else "commit",
                        "sha": self.sha,
                    }
                }
            if path == f"git/tags/{SHA}":
                return {"object": {"type": "commit", "sha": self.sha}}
            if path == "actions/artifacts/456":
                return {"expired": self.expired, "workflow_run": {"id": 123}}
            if path == "actions/runs/123":
                return {"path": ".github/workflows/release.yml"}
            if path in ("releases/17", "releases/latest"):
                return self.current
            raise AssertionError(path)
        assert data is not None
        self.writes.append((method, path, data))
        if method == "POST":
            self.current = {
                **data,
                "id": 17,
                "author": {"login": "github-actions[bot]"},
                "upload_url": "https://uploads.github.com/example",
            }
        elif method == "PATCH":
            assert self.current is not None
            self.current.update(data)
        else:
            raise AssertionError(method)
        return self.current

    def assets(self, release_id):
        return self.uploaded.copy()

    def asset_digest(self, asset):
        if asset["state"] != "uploaded":
            raise ValueError("Incomplete asset")
        return asset["digest"][7:]

    def upload(self, item, path):
        if self.fail_upload == len(self.uploaded):
            raise ConnectionError("simulated interruption")
        self.uploaded.append(
            {
                "name": path.name,
                "digest": "sha256:" + release.digest(path),
                "state": "uploaded",
                "id": len(self.uploaded) + 1,
            }
        )


@pytest.mark.parametrize("tag", ["v1.2.3", "v0.2.0"])
def test_valid_release_tags(tag):
    assert release.tag_version(tag) == tag[1:]


@pytest.mark.parametrize(
    "tag", ["1.2.3", "v01.2.3", "v1.2", "v1.2.3rc1", "v1.2.3\n", "v1.2.3;echo injected"]
)
def test_invalid_tags_rejected_before_api_access(tag):
    with pytest.raises(ValueError):
        release.resolve(FakeGitHub(), tag)


@pytest.mark.parametrize("annotated", [False, True])
def test_resolve_lightweight_and_annotated_tags(annotated):
    api = FakeGitHub()
    api.annotated = annotated
    assert release.resolve(api, TAG)["sha"] == SHA
    assert api.writes == []


def test_missing_tag_fails():
    class MissingTag(FakeGitHub):
        def request(self, method: str, path: str, data: dict[str, Any] | None = None):
            raise urllib.error.HTTPError(
                "https://api.github.com", 404, "Missing", HTTPMessage(), None
            )

    with pytest.raises(urllib.error.HTTPError):
        release.resolve(MissingTag(), TAG)


def test_package_version_must_match_tag(release_bundle):
    wheel = next(release_bundle.glob("*.whl"))
    sdist = next(release_bundle.glob("*.tar.gz"))
    with pytest.raises(ValueError, match="version"):
        release.package_version(wheel, sdist, "3.2.2")


def test_sdist_metadata_must_be_a_readable_file(release_bundle):
    wheel = next(release_bundle.glob("*.whl"))
    sdist = next(release_bundle.glob("*.tar.gz"))
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo("vic3_state_merger-3.2.1/PKG-INFO")
        member.type = tarfile.DIRTYPE
        archive.addfile(member)
    with pytest.raises(ValueError, match="PKG-INFO must be a regular file"):
        release.package_version(wheel, sdist)


@pytest.mark.parametrize("version", ["0.0.0", "3.2.2"])
def test_fallback_or_disagreeing_distribution_versions_fail(release_bundle, version):
    wheel = next(release_bundle.glob("*.whl"))
    sdist = next(release_bundle.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in entries.items():
            if name.endswith("/METADATA"):
                data = data.replace(b"Version: 3.2.1", f"Version: {version}".encode())
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="version"):
        release.package_version(wheel, sdist)


@pytest.mark.parametrize("mismatch", ["manifest", "run"])
def test_downloaded_original_bundle_is_verified_before_execution(
    release_bundle, monkeypatch, mismatch
):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    command = [
        "release_pipeline.py",
        "verify",
        "--tag",
        TAG,
        "--sha",
        SHA,
        "--bundle",
        str(release_bundle),
        "--manifest-sha256",
        "b" * 64
        if mismatch == "manifest"
        else release.digest(release_bundle / release.MANIFEST),
        "--run-id",
        "999" if mismatch == "run" else "123",
    ]
    monkeypatch.setattr(sys, "argv", command)
    with pytest.raises(ValueError, match="Downloaded bundle"):
        release.main()


@pytest.mark.parametrize("change", ["missing", "corrupt", "extra", "provenance"])
def test_bundle_rejects_missing_corrupt_and_unexpected_files(release_bundle, change):
    exe = release_bundle / "state-merger.exe"
    if change == "missing":
        exe.unlink()
    elif change == "corrupt":
        exe.write_bytes(b"modified")
    elif change == "extra":
        (release_bundle / "extra.txt").write_text("unexpected")
    else:
        info = json.loads((release_bundle / release.MANIFEST).read_text())
        info["sha"] = "b" * 40
        (release_bundle / release.MANIFEST).write_text(json.dumps(info))
    with pytest.raises(ValueError):
        release.verify_bundle(release_bundle, REPOSITORY, TAG, SHA)


def test_new_release_is_complete_before_publication(release_bundle):
    api = FakeGitHub()
    release.publish(api, release_bundle, TAG, SHA, "456")
    assert api.current is not None
    assert len(api.uploaded) == 7
    assert api.writes[0][2]["draft"] is True
    assert api.writes[-1][0] == "PATCH"
    assert api.current["draft"] is False


def interrupted_release(target):
    api = FakeGitHub()
    api.fail_upload = 2
    with pytest.raises(ConnectionError):
        release.publish(api, target, TAG, SHA, "456")
    assert api.current is not None
    assert api.current["draft"] is True
    api.fail_upload = None
    return api


def test_resume_reuses_original_bundle_and_skips_identical_assets(release_bundle):
    api = interrupted_release(release_bundle)
    original = list(api.uploaded)
    resolved = release.resolve(api, TAG)
    assert (resolved["mode"], resolved["run_id"], resolved["artifact_id"]) == (
        "resume",
        "123",
        "456",
    )
    release.publish(api, release_bundle, TAG, SHA, "456")
    assert api.uploaded[:2] == original
    assert len(api.uploaded) == 7
    assert sum(method == "POST" for method, _, _ in api.writes) == 1


@pytest.mark.parametrize(
    "conflict", ["bytes", "unexpected", "incomplete", "artifact", "source", "foreign"]
)
def test_resume_conflict_never_overwrites_or_publishes(release_bundle, conflict):
    api = interrupted_release(release_bundle)
    artifact_id = "456"
    assert api.current is not None
    if conflict == "bytes":
        api.uploaded[0]["digest"] = "sha256:" + "b" * 64
    elif conflict == "unexpected":
        api.uploaded[0]["name"] = "foreign.txt"
    elif conflict == "incomplete":
        api.uploaded[0]["state"] = "starter"
    elif conflict == "artifact":
        artifact_id = "789"
    elif conflict == "source":
        api.sha = "b" * 40
    else:
        api.current["author"]["login"] = "maintainer"
    before = list(api.writes)
    with pytest.raises(ValueError):
        release.publish(api, release_bundle, TAG, SHA, artifact_id)
    assert api.writes == before
    assert api.current["draft"] is True


def test_expired_original_artifact_fails_resolution(release_bundle):
    api = interrupted_release(release_bundle)
    api.expired = True
    with pytest.raises(ValueError, match="expired"):
        release.resolve(api, TAG)


def test_published_release_is_a_noop(release_bundle):
    api = FakeGitHub()
    release.publish(api, release_bundle, TAG, SHA, "456")
    writes, assets = list(api.writes), list(api.uploaded)
    assert release.resolve(api, TAG)["mode"] == "published"
    release.publish(api, release_bundle, TAG, SHA, "789")
    assert (api.writes, api.uploaded) == (writes, assets)


def test_auto_tag_draft_interruption_and_published_rerun_share_original_intent(
    release_bundle, tmp_path
):
    class AutomatedTagAPI(FakeGitHub):
        def __init__(self):
            super().__init__()
            self.has_tag = False
            self.tag_object: dict[str, Any] = {}

        def request(self, method: str, path: str, data: dict[str, Any] | None = None):
            if method == "GET" and path == "git/matching-refs/tags/":
                return [{"ref": "refs/tags/v3.2.0"}]
            if method == "GET" and path == f"git/ref/tags/{TAG}" and not self.has_tag:
                raise urllib.error.HTTPError(
                    "fixture", 404, "Missing", HTTPMessage(), None
                )
            if method == "GET" and path == f"git/tags/{SHA}":
                return self.tag_object
            if method == "POST" and path in ("git/tags", "git/refs"):
                assert data is not None
                self.writes.append((method, path, data.copy()))
                if path == "git/tags":
                    self.tag_object = {
                        "sha": SHA,
                        "tag": data["tag"],
                        "message": data["message"],
                        "object": {"type": "commit", "sha": data["object"]},
                    }
                else:
                    self.has_tag, self.annotated = True, True
                return {"sha": SHA}
            return super().request(method, path, data)

    api = AutomatedTagAPI()
    path = tmp_path / "intent" / release.INTENT
    info = release.prepare_intent(api, path, "123", SHA, "patch")
    assert info["tag"] == TAG
    release.create_tag(api, info)
    api.fail_upload = 2
    with pytest.raises(ConnectionError):
        release.publish(api, release_bundle, TAG, SHA, "456")
    assets = api.uploaded.copy()
    api.fail_upload = None
    reused = release.prepare_intent(api, path, "123", SHA, "patch", reuse=True)
    assert release.create_tag(api, reused) == "reused"
    assert release.resolve(api, TAG)["mode"] == "resume"
    release.publish(api, release_bundle, TAG, SHA, "456")
    assert api.uploaded[:2] == assets
    writes, assets = api.writes.copy(), api.uploaded.copy()
    assert release.create_tag(api, reused) == "reused"
    assert release.resolve(api, TAG)["mode"] == "published"
    assert (api.writes, api.uploaded) == (writes, assets)


def test_tag_move_during_upload_prevents_publication(release_bundle):
    class MovingTag(FakeGitHub):
        def upload(self, item, path):
            super().upload(item, path)
            self.sha = "b" * 40

    api = MovingTag()
    with pytest.raises(ValueError, match="tag changed"):
        release.publish(api, release_bundle, TAG, SHA, "456")
    assert api.current is not None
    assert api.current["draft"] is True


def test_latest_wheel_uses_latest_release_not_requested_tag():
    api = FakeGitHub()
    api.current = {"id": 17, "tag_name": "v4.0.0", "draft": False, "prerelease": False}
    url = f"https://github.com/{REPOSITORY}/releases/download/v4.0.0/vic3_state_merger-4.0.0-py3-none-any.whl"
    api.uploaded = [
        {
            "name": "vic3_state_merger-4.0.0-py3-none-any.whl",
            "state": "uploaded",
            "browser_download_url": url,
        }
    ]
    assert release.latest_wheel(api) == ("4.0.0", url)


def test_readme_sync_refuses_non_actions_checkout(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError, match="dedicated Actions"):
        release.sync_readmes(FakeGitHub(), tmp_path, "main")


def test_readme_permission_failure_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tmp_path / "docs").mkdir()
    url = "https://github.com/ShabbyGayBar/StateMerger/releases/download/v2.1.2/vic3_state_merger-2.1.2-py3-none-any.whl"
    for name in ("README.md", "docs/README_zh-CN.md"):
        (tmp_path / name).write_text(url)
    monkeypatch.setattr(
        release, "latest_wheel", lambda api: ("3.2.1", url.replace("2.1.2", "3.2.1"))
    )
    pushes = []

    def git(command, **kwargs):
        code = int(command[1] in ("push", "diff"))
        if command[1] == "push":
            pushes.append(command)
        stdout = SHA if command[1] in ("rev-parse", "ls-remote") else ""
        return subprocess.CompletedProcess(command, code, stdout, "")

    monkeypatch.setattr(release.subprocess, "run", git)
    with pytest.raises(ValueError, match="permissions"):
        release.sync_readmes(FakeGitHub(), tmp_path, "main")
    assert len(pushes) == 1


def test_both_readmes_update_automatically_without_downgrade(tmp_path):
    old = "https://github.com/ShabbyGayBar/StateMerger/releases/download/v2.1.2/vic3_state_merger-2.1.2-py3-none-any.whl"
    new = "https://github.com/ShabbyGayBar/StateMerger/releases/download/v4.0.0/vic3_state_merger-4.0.0-py3-none-any.whl"
    for name in ("README.md", "README_zh-CN.md"):
        path = tmp_path / name
        path.write_text(f'pip install "{old}"')
        sync_version_from_tag.update_readme(path, "4.0.0", new)
        assert new in path.read_text()


def test_readme_retry_refreshes_branch_and_latest_release(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tmp_path / "docs").mkdir()
    old = "https://github.com/ShabbyGayBar/StateMerger/releases/download/v2.1.2/vic3_state_merger-2.1.2-py3-none-any.whl"
    for name in ("README.md", "docs/README_zh-CN.md"):
        (tmp_path / name).write_text(old)
    versions = iter(
        [
            ("3.0.0", old.replace("2.1.2", "3.0.0")),
            ("4.0.0", old.replace("2.1.2", "4.0.0")),
        ]
    )
    monkeypatch.setattr(release, "latest_wheel", lambda api: next(versions))
    commands = []
    pushes = 0

    def git(command, **kwargs):
        nonlocal pushes
        commands.append(command)
        stdout = ""
        code = 0
        if command[1] == "rev-parse":
            stdout = SHA
        elif command[1] == "diff":
            code = 1
        elif command[1] == "push":
            pushes += 1
            code = int(pushes == 1)
        elif command[1] == "ls-remote":
            stdout = "b" * 40 + "\trefs/heads/main"
        return subprocess.CompletedProcess(command, code, stdout, "")

    monkeypatch.setattr(release.subprocess, "run", git)
    release.sync_readmes(FakeGitHub(), tmp_path, "main")
    assert pushes == 2
    assert sum(command[1] == "fetch" for command in commands) == 2
    assert all("--force" not in command for command in commands)
    assert "v4.0.0" in (tmp_path / "README.md").read_text()


def test_download_redirect_does_not_forward_token():
    request = urllib.request.Request(
        "https://api.github.com/asset", headers={"Authorization": "Bearer test"}
    )
    redirected = release.SafeRedirect().redirect_request(
        request,
        io.BytesIO(),
        302,
        "redirect",
        HTTPMessage(),
        "https://release-assets.githubusercontent.com/asset",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
