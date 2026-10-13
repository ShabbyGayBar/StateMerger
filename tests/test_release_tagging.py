# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Automatic tag allocation and recovery without touching a remote repository."""

import hashlib
import io
import json
import sys
import urllib.error
import zipfile
from http.client import HTTPMessage
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import release_pipeline as release

pytestmark = pytest.mark.unit
SHA = "a" * 40
REPOSITORY = "owner/StateMerger"


def http_error(code):
    return urllib.error.HTTPError(
        "https://api.github.com", code, "fixture", HTTPMessage(), None
    )


class TagAPI:
    repository = REPOSITORY

    def __init__(self, tags=None):
        self.refs: dict[str, dict[str, Any]] = {
            tag: {"type": "commit", "sha": SHA}
            for tag in (tags if tags is not None else ["v2.1.2"])
        }
        self.objects: dict[str, dict[str, Any]] = {}
        self.writes = []
        self.artifacts: list[dict[str, Any]] = []
        self.ref_failure = ""

    def request(self, method: str, path: str, data: dict[str, Any] | None = None):
        if method == "GET":
            if path == "git/matching-refs/tags/":
                return [
                    {"ref": f"refs/tags/{tag}", "object": obj}
                    for tag, obj in self.refs.items()
                ]
            if path.startswith("git/ref/tags/"):
                tag = path.removeprefix("git/ref/tags/")
                if tag not in self.refs:
                    raise http_error(404)
                return {"object": self.refs[tag]}
            if path.startswith("git/tags/"):
                return self.objects[path.removeprefix("git/tags/")]
            if path.startswith("actions/runs/123/artifacts?"):
                page = int(path.rsplit("=", 1)[1])
                return {"artifacts": self.artifacts[(page - 1) * 100 : page * 100]}
            raise AssertionError(path)
        assert data is not None
        self.writes.append((method, path, data.copy()))
        assert method == "POST", "Tags must never be updated or deleted"
        if path == "git/tags":
            sha = f"{len(self.objects) + 1:040x}"
            self.objects[sha] = {
                "sha": sha,
                "tag": data["tag"],
                "message": data["message"],
                "object": {
                    "type": data["type"],
                    "sha": data["object"],
                    "url": "fixture",
                },
            }
            return self.objects[sha]
        if path == "git/refs":
            if self.ref_failure == "before":
                raise TimeoutError("interrupted before reference creation")
            tag = data["ref"].removeprefix("refs/tags/")
            if tag in self.refs:
                raise http_error(422)
            self.refs[tag] = {"type": "tag", "sha": data["sha"]}
            if self.ref_failure == "after":
                raise TimeoutError("reference created; response lost")
            return {"object": self.refs[tag]}
        raise AssertionError(path)


def intent(path, api=None, run_id="123", bump="patch", sha=SHA):
    return release.prepare_intent(
        api or TagAPI(), path / release.INTENT, run_id, sha, bump
    )


@pytest.mark.parametrize(
    "bump,expected", [("patch", "v2.10.4"), ("minor", "v2.11.0"), ("major", "v3.0.0")]
)
def test_bump_uses_numeric_highest_remote_stable_tag(bump, expected):
    api = TagAPI(
        [
            "v2.9.9",
            "v2.10.3",
            "v1.99.99",
            "v99.0.0rc1",
            "v99.0.0-beta",
            "v02.0.0",
            "99.0.0",
        ]
    )
    # No release API is consulted: unpublished and lightweight tags count too.
    assert release.next_tag(api, bump) == expected
    api.refs["v2.10.3"]["type"] = "tag"
    assert release.next_tag(api, bump) == expected
    assert api.writes == []


def test_no_stable_base_or_unknown_bump_fails():
    with pytest.raises(ValueError, match="No canonical stable tag"):
        release.next_tag(TagAPI(["v1.0.0rc1"]), "patch")
    with pytest.raises(ValueError, match="Bump"):
        release.next_tag(TagAPI(), "feature")


def dispatch(**inputs):
    return {"repository": {"default_branch": "master"}, "inputs": inputs}


def test_new_dispatch_pins_default_branch_snapshot():
    selection = release.select_source(
        "workflow_dispatch", dispatch(), "refs/heads/master", SHA
    )
    assert selection == {"operation": "new", "bump": "patch", "sha": SHA, "tag": ""}


@pytest.mark.parametrize(
    "event,ref,sha",
    [
        (dispatch(), "refs/heads/topic", SHA),
        (dispatch(release_tag="v2.1.3"), "refs/heads/master", SHA),
        (dispatch(operation="other"), "refs/heads/master", SHA),
        (dispatch(bump="feature"), "refs/heads/master", SHA),
        (dispatch(operation="existing"), "refs/heads/master", SHA),
        (
            dispatch(operation="existing", release_tag="v1.0.0rc1"),
            "refs/heads/master",
            SHA,
        ),
        (dispatch(), "refs/heads/master", "invalid"),
    ],
)
def test_invalid_dispatch_rejected(event, ref, sha):
    with pytest.raises(ValueError):
        release.select_source("workflow_dispatch", event, ref, sha)


def test_existing_dispatch_and_push_keep_manual_tag_support():
    selection = release.select_source(
        "workflow_dispatch",
        dispatch(operation="existing", release_tag="v2.1.2", bump="ignored"),
        "refs/heads/topic",
        SHA,
    )
    assert (selection["operation"], selection["tag"], selection["bump"]) == (
        "existing",
        "v2.1.2",
        "",
    )
    assert release.select_source("push", {}, "refs/tags/v2.1.2", SHA) == selection
    with pytest.raises(ValueError, match="tag"):
        release.select_source("push", {}, "refs/heads/master", SHA)
    with pytest.raises(ValueError, match="Unsupported"):
        release.select_source("pull_request", {}, "refs/heads/master", SHA)


def artifact(**changes):
    return {
        "id": 456,
        "name": "release-intent-123",
        "expired": False,
        "workflow_run": {"id": 123},
        **changes,
    }


def test_intent_lookup_finds_original_across_pages():
    api = TagAPI()
    assert release.find_intent(api, "123", "1") == ""
    api.artifacts = [artifact(name=f"unrelated-{index}") for index in range(100)] + [
        artifact()
    ]
    assert release.find_intent(api, "123", "2") == "456"


@pytest.mark.parametrize(
    "artifacts",
    [
        [],
        [artifact(expired=True)],
        [artifact(), artifact(id=789)],
        [artifact(workflow_run={"id": 999})],
        [artifact(id="invalid")],
    ],
)
def test_missing_expired_or_ambiguous_retry_intent_fails(artifacts):
    api = TagAPI()
    api.artifacts = artifacts
    with pytest.raises(ValueError, match="intent"):
        release.find_intent(api, "123", "2")


@pytest.mark.parametrize("run_id,attempt", [("invalid", "1"), ("123", "0")])
def test_invalid_run_identifiers_fail_before_api_access(run_id, attempt):
    with pytest.raises(ValueError, match="identifiers"):
        release.find_intent(TagAPI(), run_id, attempt)


@pytest.mark.parametrize(
    "failure",
    ["", "digest", "missing-digest", "expired", "foreign", "extra", "duplicate"],
)
def test_intent_archive_integrity_checked_before_recovery(tmp_path, failure):
    info = intent(tmp_path / "original")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(release.INTENT, json.dumps(info))
        if failure == "extra":
            archive.writestr("../extra", "unexpected")
        elif failure == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(release.INTENT, json.dumps(info))
    contents = stream.getvalue()
    metadata = artifact(digest="sha256:" + hashlib.sha256(contents).hexdigest())
    if failure == "digest":
        contents += b"corrupt bytes"
    elif failure == "missing-digest":
        metadata.pop("digest")
    elif failure == "expired":
        metadata["expired"] = True
    elif failure == "foreign":
        metadata["workflow_run"] = {"id": 999}

    class ArchiveAPI(TagAPI):
        def request(self, method: str, path: str, data: dict[str, Any] | None = None):
            assert (method, path) == ("GET", "actions/artifacts/456")
            return metadata

        def open(self, method, url):
            assert method == "GET" and url.endswith("/actions/artifacts/456/zip")
            return io.BytesIO(contents)

    api = ArchiveAPI()
    path = tmp_path / "downloaded" / release.INTENT
    if failure:
        with pytest.raises(ValueError, match="intent"):
            release.download_intent(api, "456", "123", path)
        assert not path.exists()
    else:
        release.download_intent(api, "456", "123", path)
        assert (
            release.prepare_intent(api, path, "123", SHA, "patch", reuse=True) == info
        )


def test_rerun_uses_saved_intent_even_when_newer_tags_exist(tmp_path):
    api = TagAPI()
    path = tmp_path / "intent"
    original = intent(path, api)
    api.refs["v9.0.0"] = {"type": "commit", "sha": "b" * 40}
    assert (
        release.prepare_intent(
            api, path / release.INTENT, "123", SHA, "patch", reuse=True
        )
        == original
    )
    assert original["tag"] == "v2.1.3"
    assert api.writes == []


@pytest.mark.parametrize(
    "change",
    [
        "sha",
        "run_id",
        "repository",
        "bump",
        "tag",
        "schema",
        "json",
        "extra",
        "missing",
    ],
)
def test_corrupt_or_mismatched_intent_fails(tmp_path, change):
    path = tmp_path / "intent"
    info = intent(path)
    file = path / release.INTENT
    if change == "json":
        file.write_text("broken JSON")
    elif change == "extra":
        (path / "unexpected").write_text("extra")
    elif change == "missing":
        file.unlink()
    else:
        info[change] = "invalid"
        file.write_text(json.dumps(info))
    with pytest.raises(ValueError):
        release.prepare_intent(TagAPI(), file, "123", SHA, "patch", reuse=True)


def test_new_tag_is_annotated_and_rerun_makes_no_writes(tmp_path):
    api = TagAPI()
    info = intent(tmp_path / "intent", api)
    assert release.create_tag(api, info) == "created"
    assert release.resolve_tag(api, info["tag"]) == SHA
    writes = api.writes.copy()
    assert [path for _, path, _ in writes] == ["git/tags", "git/refs"]
    assert release.create_tag(api, info) == "reused"
    assert api.writes == writes
    assert info["sha"] in writes[0][2]["message"]
    assert "/actions/runs/123" in writes[0][2]["message"]


@pytest.mark.parametrize("failure", ["before", "after"])
def test_interrupted_reference_creation_retains_version(tmp_path, failure):
    api = TagAPI()
    info = intent(tmp_path / "intent", api)
    api.ref_failure = failure
    if failure == "before":
        with pytest.raises(TimeoutError):
            release.create_tag(api, info)
        assert info["tag"] not in api.refs
    else:
        assert release.create_tag(api, info) == "created"
    api.ref_failure = ""
    release.create_tag(api, info)
    assert release.resolve_tag(api, info["tag"]) == SHA
    assert set(api.refs) == {"v2.1.2", "v2.1.3"}


@pytest.mark.parametrize("conflict", ["lightweight", "owner", "source", "tag"])
def test_existing_conflicting_tag_is_never_replaced(tmp_path, conflict):
    api = TagAPI()
    info = intent(tmp_path / "intent", api)
    release.create_tag(api, info)
    obj = api.objects[api.refs[info["tag"]]["sha"]]
    if conflict == "lightweight":
        api.refs[info["tag"]] = {"type": "commit", "sha": SHA}
    elif conflict == "owner":
        obj["message"] = "maintainer's annotation"
    elif conflict == "source":
        obj["object"]["sha"] = "b" * 40
    else:
        obj["tag"] = "v2.1.4"
    writes = api.writes.copy()
    with pytest.raises(ValueError, match="Conflicting"):
        release.create_tag(api, info)
    assert api.writes == writes


def test_concurrent_external_allocation_conflict_fails_closed(tmp_path):
    api = TagAPI()
    first = intent(tmp_path / "first", api)
    other = intent(tmp_path / "other", api, run_id="999")
    assert first["tag"] == other["tag"]
    release.create_tag(api, first)
    before = api.writes.copy()
    with pytest.raises(ValueError, match="Conflicting"):
        release.create_tag(api, other)
    assert api.writes == before
    # A separate dispatch after the first allocation sees the reserved tag.
    assert intent(tmp_path / "next", api, run_id="1000")["tag"] == "v2.1.4"


def test_conflict_during_reference_creation_is_not_overwritten(tmp_path):
    class RacingAPI(TagAPI):
        def request(self, method: str, path: str, data: dict[str, Any] | None = None):
            if method == "POST" and path == "git/refs":
                assert data is not None
                self.refs[data["ref"].removeprefix("refs/tags/")] = {
                    "type": "commit",
                    "sha": SHA,
                }
            return super().request(method, path, data)

    api = RacingAPI()
    info = intent(tmp_path / "intent", api)
    with pytest.raises(ValueError, match="Conflicting"):
        release.create_tag(api, info)
    assert all(method == "POST" for method, _, _ in api.writes)
    assert api.refs[info["tag"]]["type"] == "commit"


def test_resolve_rejects_tag_moved_after_preparation(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setattr(release, "resolve", lambda api, tag: {"sha": "b" * 40})
    monkeypatch.setattr(
        sys, "argv", ["release_pipeline.py", "resolve", "--tag", "v2.1.3", "--sha", SHA]
    )
    with pytest.raises(ValueError, match="pinned dispatch"):
        release.main()


def test_summary_explains_selected_version_and_recovery(monkeypatch, tmp_path):
    path = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    release.release_summary("v2.1.3", SHA, "patch", "Tag created")
    text = path.read_text()
    assert all(
        value in text
        for value in ("v2.1.3", "2.1.3", "patch", SHA, "operation: existing", "rerun")
    )


def test_workflow_persists_intent_before_tagging_and_keeps_publication_gates():
    workflow = yaml.load(
        (Path(__file__).parents[1] / ".github/workflows/release.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert workflow["concurrency"] == {
        "group": "release-${{ github.repository }}",
        "cancel-in-progress": "false",
    }
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["operation"]["options"] == ["new", "existing"]
    assert inputs["bump"]["options"] == ["patch", "minor", "major"]
    assert inputs["release_tag"]["required"] == "false"
    steps = workflow["jobs"]["prepare"]["steps"]
    save = next(
        index
        for index, step in enumerate(steps)
        if "upload-artifact" in step.get("uses", "")
    )
    create = next(
        index for index, step in enumerate(steps) if "create-tag" in step.get("run", "")
    )
    assert save < create
    assert steps[save]["with"]["retention-days"] == "90"
    assert "always()" not in steps[create].get("if", "")
    assert workflow["jobs"]["resolve"]["needs"] == "prepare"
    assert "--sha" in workflow["jobs"]["resolve"]["steps"][-1]["run"]
    assert (
        "needs.prepare.outputs.operation == 'new'"
        in workflow["jobs"]["sync-readme-version"]["if"]
    )
