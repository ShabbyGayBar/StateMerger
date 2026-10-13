# Copyright (C) 2025-2026 Brian Li
# SPDX-License-Identifier: GPL-3.0-or-later

"""Release policy and GitHub transport. All build inputs come from a resolved tag."""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path

MANIFEST = "release-manifest.json"
INTENT = "release-intent.json"
MARKER = re.compile(r"<!-- state-merger-release:(\{[^\n]*\}) -->")
FIXED_FILES = {
    "state-merger.exe",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "merge_states.json",
}


def tag_version(tag):
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError("Release tag must be vX.Y.Z without leading zeroes")
    return tag[1:]


def select_source(event_name, event, ref, sha):
    """Validate dispatch inputs before any remote mutation or version allocation."""
    inputs = event.get("inputs") or {}
    if event_name == "push":
        if not ref.startswith("refs/tags/"):
            raise ValueError("Release pushes must reference a tag")
        operation, tag, bump = "existing", ref.removeprefix("refs/tags/"), ""
    elif event_name == "workflow_dispatch":
        operation = inputs.get("operation", "new")
        tag = inputs.get("release_tag", "")
        bump = inputs.get("bump", "patch") if operation == "new" else ""
        if operation not in ("new", "existing"):
            raise ValueError("Release operation must be new or existing")
        if operation == "new":
            if tag:
                raise ValueError("New releases must not supply release_tag")
            if ref != f"refs/heads/{event['repository']['default_branch']}":
                raise ValueError("New releases must run from the default branch")
            if bump not in ("patch", "minor", "major"):
                raise ValueError("Bump must be patch, minor, or major")
    else:
        raise ValueError("Unsupported release event")
    if operation == "existing":
        tag_version(tag)
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Invalid dispatch commit SHA")
    return {"operation": operation, "tag": tag, "bump": bump, "sha": sha}


def next_tag(api, bump):
    if bump not in ("patch", "minor", "major"):
        raise ValueError("Bump must be patch, minor, or major")
    versions = []
    # Matching refs returns the complete namespace, including unpublished tags.
    for item in api.request("GET", "git/matching-refs/tags/"):
        tag = item["ref"].removeprefix("refs/tags/")
        try:
            versions.append(tuple(map(int, tag_version(tag).split("."))))
        except ValueError:
            continue
    if not versions:
        raise ValueError("No canonical stable tag exists to bump")
    major, minor, patch = max(versions)
    if bump == "major":
        major, minor, patch = major + 1, 0, 0
    elif bump == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"v{major}.{minor}.{patch}"


def find_intent(api, run_id, attempt):
    """Locate this run's immutable intent; never allocate again on a rerun."""
    if not re.fullmatch(r"[1-9]\d*", run_id) or not re.fullmatch(r"[1-9]\d*", attempt):
        raise ValueError("Invalid workflow run identifiers")
    matches = []
    page = 1
    while True:
        items = api.request(
            "GET", f"actions/runs/{run_id}/artifacts?per_page=100&page={page}"
        )["artifacts"]
        matches.extend(
            item for item in items if item["name"] == f"release-intent-{run_id}"
        )
        if len(items) < 100:
            break
        page += 1
    if not matches:
        if int(attempt) != 1:
            raise ValueError(
                "Original release intent is unavailable; use an existing tag or a new dispatch"
            )
        return ""
    if (
        len(matches) != 1
        or matches[0].get("expired")
        or str(matches[0].get("workflow_run", {}).get("id")) != run_id
        or not re.fullmatch(r"[1-9]\d*", str(matches[0].get("id", "")))
    ):
        raise ValueError("Release intent is expired or has ambiguous provenance")
    return str(matches[0]["id"])


def validate_intent(info, repository, run_id, sha, bump):
    if (
        not isinstance(info, dict)
        or set(info) != {"schema", "repository", "run_id", "sha", "bump", "tag"}
        or info.get("schema") != 1
        or (
            info.get("repository"),
            info.get("run_id"),
            info.get("sha"),
            info.get("bump"),
        )
        != (repository, run_id, sha, bump)
        or not re.fullmatch(r"[1-9]\d*", run_id)
        or not re.fullmatch(r"[a-f0-9]{40}", sha)
        or bump not in ("patch", "minor", "major")
        or not isinstance(info.get("tag"), str)
    ):
        raise ValueError("Release intent does not match this workflow run")
    tag_version(info["tag"])
    return info


def download_intent(api, artifact_id, run_id, path):
    """Fail on archive corruption rather than accepting a download warning."""
    if not re.fullmatch(r"[1-9]\d*", artifact_id):
        raise ValueError("Invalid release intent artifact ID")
    artifact = api.request("GET", f"actions/artifacts/{artifact_id}")
    if (
        artifact.get("name") != f"release-intent-{run_id}"
        or artifact.get("expired")
        or str(artifact.get("workflow_run", {}).get("id")) != run_id
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact.get("digest") or "")
    ):
        raise ValueError("Release intent artifact has invalid provenance or digest")
    url = f"https://api.github.com/repos/{api.repository}/actions/artifacts/{artifact_id}/zip"
    with api.open("GET", url) as response:
        data = response.read()
    if "sha256:" + hashlib.sha256(data).hexdigest() != artifact["digest"]:
        raise ValueError("Release intent archive digest mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist() != [INTENT] or archive.getinfo(INTENT).is_dir():
            raise ValueError(
                "Release intent archive must contain exactly its JSON file"
            )
        contents = archive.read(INTENT)
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_bytes(contents)


def prepare_intent(api, path, run_id, sha, bump, reuse=False):
    if reuse:
        if (
            path.is_symlink()
            or not path.is_file()
            or set(path.parent.iterdir()) != {path}
        ):
            raise ValueError("Downloaded intent must contain exactly one regular file")
        return validate_intent(
            json.loads(path.read_text(encoding="utf-8")),
            api.repository,
            run_id,
            sha,
            bump,
        )
    info = validate_intent(
        {
            "schema": 1,
            "repository": api.repository,
            "run_id": run_id,
            "sha": sha,
            "bump": bump,
            "tag": next_tag(api, bump),
        },
        api.repository,
        run_id,
        sha,
        bump,
    )
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return info


def intent_annotation(info):
    return (
        f"Release {info['tag']}\n\n"
        f"Source: {info['sha']}\n"
        f"Run: https://github.com/{info['repository']}/actions/runs/{info['run_id']}\n\n"
        f"state-merger-release-intent:{json.dumps(info, sort_keys=True)}\n"
    )


def create_tag(api, info):
    """Create only; an existing reference must belong to this exact intent."""
    validate_intent(info, api.repository, info["run_id"], info["sha"], info["bump"])

    def owned_tag_exists():
        try:
            ref = api.request("GET", f"git/ref/tags/{info['tag']}")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return False
            raise
        obj = ref["object"]
        if obj["type"] != "tag":
            raise ValueError("Conflicting release tag is not workflow annotated")
        annotated = api.request("GET", f"git/tags/{obj['sha']}")
        if (
            annotated.get("tag") != info["tag"]
            or annotated.get("message") != intent_annotation(info)
            or annotated.get("object", {}).get("type") != "commit"
            or annotated.get("object", {}).get("sha") != info["sha"]
            or resolve_tag(api, info["tag"]) != info["sha"]
        ):
            raise ValueError("Conflicting release tag does not belong to this intent")
        return True

    if owned_tag_exists():
        return "reused"
    annotated = api.request(
        "POST",
        "git/tags",
        {
            "tag": info["tag"],
            "message": intent_annotation(info),
            "object": info["sha"],
            "type": "commit",
        },
    )
    try:
        api.request(
            "POST",
            "git/refs",
            {"ref": f"refs/tags/{info['tag']}", "sha": annotated["sha"]},
        )
    except OSError:
        # A conflict or lost response may follow successful creation. Inspect the
        # reference; never retry by updating it or selecting a different version.
        if not owned_tag_exists():
            raise
    if not owned_tag_exists():
        raise ValueError("Tag creation did not produce the expected remote reference")
    return "created"


def release_summary(tag, sha, bump, state):
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as output:
            output.write(
                f"### Release {tag}\n\n"
                f"- Bump: `{bump or 'existing tag'}`\n"
                f"- Version: `{tag_version(tag)}`\n"
                f"- Source: `{sha}`\n"
                f"- State: {state}\n\n"
                "Recovery: rerun this workflow run to keep its version, or dispatch "
                f"Release with `operation: existing` and `release_tag: {tag}`. "
                "If the original intent is unavailable and no tag exists, start a new dispatch. "
                "A new dispatch with `operation: new` selects another version.\n\n"
            )


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            redirected
            and urllib.parse.urlsplit(req.full_url).netloc
            != urllib.parse.urlsplit(newurl).netloc
        ):
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, repository, token=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Expected owner/repository")
        self.repository = repository
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.opener = urllib.request.build_opener(SafeRedirect())

    def request(self, method, path, data=None):
        payload = json.dumps(data).encode() if data is not None else None
        url = f"https://api.github.com/repos/{self.repository}/{path}"
        with self.open(method, url, payload) as response:
            return json.load(response)

    def open(self, method, url, data=None, accept="application/vnd.github+json"):
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "StateMerger-release",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = (
                "application/octet-stream"
                if urllib.parse.urlsplit(url).hostname == "uploads.github.com"
                else "application/json"
            )
        return self.opener.open(
            urllib.request.Request(url, data=data, headers=headers, method=method),
            timeout=60,
        )

    def release(self, tag):
        # The tag endpoint does not return drafts. Paginate rather than assuming
        # that an interrupted draft is among the most recent releases.
        try:
            return self.request("GET", f"releases/tags/{tag}")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        page = 1
        while True:
            releases = self.request("GET", f"releases?per_page=100&page={page}")
            matches = [item for item in releases if item["tag_name"] == tag]
            if len(matches) > 1:
                raise ValueError("Multiple releases have the requested tag")
            if matches:
                return matches[0]
            if len(releases) < 100:
                return None
            page += 1

    def assets(self, release_id):
        result = []
        page = 1
        while True:
            items = self.request(
                "GET", f"releases/{release_id}/assets?per_page=100&page={page}"
            )
            result.extend(items)
            if len(items) < 100:
                return result
            page += 1

    def asset_digest(self, asset):
        if asset.get("state") != "uploaded":
            raise ValueError(f"Incomplete uploaded asset: {asset['name']}")
        if re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or ""):
            return asset["digest"][7:]
        url = f"https://api.github.com/repos/{self.repository}/releases/assets/{asset['id']}"
        with self.open("GET", url, accept="application/octet-stream") as response:
            return hashlib.file_digest(response, "sha256").hexdigest()

    def upload(self, release, path):
        url = release["upload_url"].split("{")[0]
        if urllib.parse.urlsplit(url).hostname != "uploads.github.com":
            raise ValueError("Unexpected GitHub upload URL")
        url += "?" + urllib.parse.urlencode({"name": path.name})
        with self.open("POST", url, path.read_bytes()) as response:
            return json.load(response)


def resolve_tag(api, tag):
    tag_version(tag)
    obj = api.request("GET", f"git/ref/tags/{tag}")["object"]
    for _ in range(10):
        if obj["type"] == "commit":
            if not re.fullmatch(r"[a-f0-9]{40}", obj["sha"]):
                break
            return obj["sha"]
        if obj["type"] != "tag":
            break
        obj = api.request("GET", f"git/tags/{obj['sha']}")["object"]
    raise ValueError("Tag does not resolve to a Git commit")


def draft_metadata(release, repository, tag, sha):
    match = MARKER.search(release.get("body") or "")
    if not match or release.get("author", {}).get("login") != "github-actions[bot]":
        raise ValueError("Refusing to resume a draft not created by this workflow")
    info = json.loads(match[1])
    if (
        release.get("tag_name") != tag
        or release.get("prerelease")
        or info.get("schema") != 1
        or (
            info.get("repository"),
            info.get("tag"),
            info.get("sha"),
        )
        != (repository, tag, sha)
    ):
        raise ValueError("Draft source does not match the requested release")
    for key in ("run_id", "artifact_id"):
        if not re.fullmatch(r"[1-9]\d*", str(info.get(key, ""))):
            raise ValueError("Draft has invalid artifact identifiers")
    if not re.fullmatch(r"[a-f0-9]{64}", info.get("manifest_sha256", "")):
        raise ValueError("Draft has invalid manifest digest")
    return info


def resolve(api, tag):
    sha = resolve_tag(api, tag)
    result = {
        "tag": tag,
        "sha": sha,
        "version": tag_version(tag),
        "mode": "new",
        "run_id": "",
        "artifact_id": "",
        "manifest_sha256": "",
    }
    release = api.release(tag)
    if release and not release["draft"]:
        result["mode"] = "published"
    elif release:
        info = draft_metadata(release, api.repository, tag, sha)
        artifact = api.request("GET", f"actions/artifacts/{info['artifact_id']}")
        run = api.request("GET", f"actions/runs/{info['run_id']}")
        if (
            artifact.get("expired")
            or str(artifact.get("workflow_run", {}).get("id")) != str(info["run_id"])
            or run.get("path", "").split("@")[0] != ".github/workflows/release.yml"
        ):
            raise ValueError(
                "Original release bundle is expired or has invalid provenance"
            )
        result.update(
            mode="resume",
            run_id=str(info["run_id"]),
            artifact_id=str(info["artifact_id"]),
            manifest_sha256=info["manifest_sha256"],
        )
    return result


def package_version(wheel, sdist, expected=None):
    with zipfile.ZipFile(wheel) as archive:
        metadata = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata) != 1:
            raise ValueError("Wheel must have one METADATA file")
        wheel_info = BytesParser().parsebytes(archive.read(metadata[0]))
        required = {
            f"vic3_state_merger/assets/{name}.py"
            for name in ("state_traits", "flag_definitions_usa", "usa_state_counter")
        }
        if not required.issubset(archive.namelist()):
            raise ValueError("Wheel is missing bundled overrides")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            if not any(
                path.endswith(f"/licenses/{name}") for path in archive.namelist()
            ):
                raise ValueError(f"Wheel is missing {name}")
    with tarfile.open(sdist) as archive:
        metadata = [
            item
            for item in archive.getmembers()
            if item.name.count("/") == 1 and item.name.endswith("/PKG-INFO")
        ]
        if len(metadata) != 1:
            raise ValueError("Sdist must have one top-level PKG-INFO")
        stream = archive.extractfile(metadata[0])
        if stream is None:
            raise ValueError("Sdist PKG-INFO must be a regular file")
        with stream:
            sdist_info = BytesParser().parsebytes(stream.read())
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            if not any(
                path.count("/") == 1 and path.endswith(f"/{name}")
                for path in archive.getnames()
            ):
                raise ValueError(f"Sdist is missing {name}")
    version = wheel_info["Version"]
    if (
        not version
        or version == "0.0.0"
        or sdist_info["Version"] != version
        or (expected is not None and version != expected)
    ):
        raise ValueError("Package version differs from release tag or is a fallback")
    for info in (wheel_info, sdist_info):
        if re.sub(r"[-_.]+", "-", info["Name"]).lower() != "vic3-state-merger":
            raise ValueError("Unexpected package name")
    if (
        wheel.name != f"vic3_state_merger-{version}-py3-none-any.whl"
        or sdist.name != f"vic3_state_merger-{version}.tar.gz"
    ):
        raise ValueError("Unexpected package filenames")
    return version


def bundle(root, dist, target, tag, sha, repository, run_id):
    wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Expected exactly one wheel and one sdist")
    version = package_version(wheels[0], sdists[0], tag_version(tag) if tag else None)
    target.mkdir(parents=True, exist_ok=False)
    files = [
        dist / "state-merger.exe",
        *wheels,
        *sdists,
        *(root / name for name in sorted(FIXED_FILES - {"state-merger.exe"})),
    ]
    for path in files:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty release file: {path.name}")
        shutil.copyfile(path, target / path.name)
    info = {
        "schema": 1,
        "repository": repository,
        "tag": tag,
        "sha": sha,
        "version": version,
        "run_id": str(run_id),
        "files": {path.name: digest(path) for path in sorted(target.iterdir())},
    }
    (target / MANIFEST).write_text(
        json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return verify_bundle(target, repository, tag, sha)


def verify_bundle(target, repository, tag, sha):
    if (target / MANIFEST).is_symlink() or not (target / MANIFEST).is_file():
        raise ValueError("Release manifest must be a regular file")
    info = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    if (
        info.get("schema") != 1
        or (info.get("repository"), info.get("tag"), info.get("sha"))
        != (repository, tag, sha)
        or not re.fullmatch(r"[a-f0-9]{40}", sha)
        or not re.fullmatch(r"[1-9]\d*", str(info.get("run_id", "")))
    ):
        raise ValueError("Bundle provenance does not match requested source")
    version = info["version"]
    expected = FIXED_FILES | {
        f"vic3_state_merger-{version}-py3-none-any.whl",
        f"vic3_state_merger-{version}.tar.gz",
    }
    if set(info["files"]) != expected or {
        path.name for path in target.iterdir()
    } != expected | {MANIFEST}:
        raise ValueError("Unexpected or missing release files")
    for name, checksum in info["files"].items():
        path = target / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size == 0
            or digest(path) != checksum
        ):
            raise ValueError(f"Release file digest mismatch: {name}")
    actual = package_version(
        target / f"vic3_state_merger-{version}-py3-none-any.whl",
        target / f"vic3_state_merger-{version}.tar.gz",
        tag_version(tag) if tag else None,
    )
    if actual != version:
        raise ValueError("Manifest version does not match packages")
    return info


def verify_assets(api, release, expected, complete=False):
    assets = api.assets(release["id"])
    names = [asset["name"] for asset in assets]
    if (
        len(set(names)) != len(names)
        or set(names) - expected.keys()
        or (complete and set(names) != expected.keys())
    ):
        raise ValueError("Unexpected, duplicate, or missing release assets")
    for asset in assets:
        if api.asset_digest(asset) != expected[asset["name"]]:
            raise ValueError(
                f"Existing asset differs from original bundle: {asset['name']}"
            )
    return set(names)


def publish(api, target, tag, sha, artifact_id):
    info = verify_bundle(target, api.repository, tag, sha)
    if resolve_tag(api, tag) != sha:
        raise ValueError("Remote release tag changed")
    release = api.release(tag)
    if release and not release["draft"]:
        return "published"
    metadata = {
        "schema": 1,
        "repository": api.repository,
        "tag": tag,
        "sha": sha,
        "run_id": info["run_id"],
        "artifact_id": str(artifact_id),
        "manifest_sha256": digest(target / MANIFEST),
    }
    if release:
        if draft_metadata(release, api.repository, tag, sha) != metadata:
            raise ValueError("Draft must reuse its original release bundle")
    else:
        body = f"Source: `{sha}`\n\nBuild: https://github.com/{api.repository}/actions/runs/{info['run_id']}\n\n<!-- state-merger-release:{json.dumps(metadata, sort_keys=True)} -->"
        release = api.request(
            "POST",
            "releases",
            {
                "tag_name": tag,
                "target_commitish": sha,
                "name": tag,
                "draft": True,
                "prerelease": False,
                "body": body,
            },
        )
    expected = {**info["files"], MANIFEST: digest(target / MANIFEST)}
    existing = verify_assets(api, release, expected)
    for name in sorted(expected.keys() - existing):
        api.upload(release, target / name)
    verify_assets(api, release, expected, complete=True)
    if resolve_tag(api, tag) != sha:
        raise ValueError("Remote release tag changed before publication")
    current = api.request("GET", f"releases/{release['id']}")
    if (
        not current["draft"]
        or draft_metadata(current, api.repository, tag, sha) != metadata
    ):
        raise ValueError("Draft changed during publication")
    api.request(
        "PATCH", f"releases/{release['id']}", {"draft": False, "make_latest": "legacy"}
    )
    return "published"


def latest_wheel(api):
    release = api.request("GET", "releases/latest")
    version = tag_version(release["tag_name"])
    if release["draft"] or release["prerelease"]:
        raise ValueError("Latest release must be published and stable")
    name = f"vic3_state_merger-{version}-py3-none-any.whl"
    assets = [
        asset
        for asset in api.assets(release["id"])
        if asset["name"] == name and asset.get("state") == "uploaded"
    ]
    if len(assets) != 1:
        raise ValueError("Latest stable release has no unique uploaded wheel")
    url = f"https://github.com/{api.repository}/releases/download/{release['tag_name']}/{name}"
    if assets[0]["browser_download_url"] != url:
        raise ValueError("Unexpected release wheel URL")
    return version, url


def sync_readmes(api, root, branch):
    # Reset only a clean, dedicated Actions checkout; retry by regenerating the
    # links against both the current branch and latest release, never force push.
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Automatic README push requires a dedicated Actions checkout")
    if __package__:
        from .sync_version_from_tag import update_readme
    else:
        from sync_version_from_tag import update_readme

    def git(*args, check=True):
        return subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=check
        )

    if git("status", "--porcelain").stdout.strip():
        raise ValueError("README checkout must start clean")
    git("check-ref-format", f"refs/heads/{branch}")
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    for _ in range(3):
        git("fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}")
        base = git("rev-parse", f"refs/remotes/origin/{branch}").stdout.strip()
        git("reset", "--hard", base)
        version, url = latest_wheel(api)
        for relative in ("README.md", "docs/README_zh-CN.md"):
            update_readme(root / relative, version, url)
        if (
            git(
                "diff",
                "--quiet",
                "--",
                "README.md",
                "docs/README_zh-CN.md",
                check=False,
            ).returncode
            == 0
        ):
            return
        git("add", "--", "README.md", "docs/README_zh-CN.md")
        git("commit", "-m", f"docs: sync README release links for v{version}")
        if (
            git("push", "origin", f"HEAD:refs/heads/{branch}", check=False).returncode
            == 0
        ):
            return
        remote = git("ls-remote", "origin", f"refs/heads/{branch}").stdout.split()
        if not remote or remote[0] == base:
            raise ValueError(
                "README push failed; check branch protection and token permissions"
            )
    raise ValueError("README push failed after three concurrent-update retries")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "select",
            "find-intent",
            "download-intent",
            "prepare-intent",
            "create-tag",
            "resolve",
            "bundle",
            "verify",
            "publish",
            "sync-readme",
        ),
    )
    parser.add_argument("--tag", default="")
    parser.add_argument("--sha", default="")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--bundle", type=Path, default=Path("release-bundle"))
    parser.add_argument("--artifact-id", default="")
    parser.add_argument("--manifest-sha256", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--bump", default="patch")
    parser.add_argument("--attempt", default="1")
    parser.add_argument("--intent", type=Path, default=Path("release-intent") / INTENT)
    args = parser.parse_args()
    api = GitHub(os.environ["GITHUB_REPOSITORY"])

    def outputs(result):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.writelines(f"{key}={value}\n" for key, value in result.items())

    if args.command == "select":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        outputs(
            select_source(
                os.environ["GITHUB_EVENT_NAME"],
                event,
                os.environ["GITHUB_REF"],
                os.environ["GITHUB_SHA"],
            )
        )
    elif args.command == "find-intent":
        outputs({"artifact_id": find_intent(api, args.run_id, args.attempt)})
    elif args.command == "download-intent":
        download_intent(api, args.artifact_id, args.run_id, args.intent)
    elif args.command in ("prepare-intent", "create-tag"):
        if args.command == "prepare-intent":
            info = prepare_intent(
                api,
                args.intent,
                args.run_id,
                args.sha,
                args.bump,
                reuse=bool(args.artifact_id),
            )
            outputs({"tag": info["tag"]})
            state = "Intent selected; tag creation requires successful intent upload"
        else:
            info = validate_intent(
                json.loads(args.intent.read_text(encoding="utf-8")),
                api.repository,
                args.run_id,
                args.sha,
                args.bump,
            )
            state = "Tag " + create_tag(api, info)
        release_summary(info["tag"], info["sha"], info["bump"], state)
    elif args.command == "resolve":
        result = resolve(api, args.tag)
        if args.sha and result["sha"] != args.sha:
            raise ValueError("Remote tag differs from the pinned dispatch source")
        outputs(result)
        release_summary(
            args.tag, result["sha"], os.environ.get("RELEASE_BUMP", ""), result["mode"]
        )
        print(f"Release {result['tag']}: {result['sha']} ({result['mode']})")
    elif args.command == "bundle":
        bundle(
            args.root,
            args.dist,
            args.bundle,
            args.tag,
            args.sha,
            api.repository,
            os.environ["GITHUB_RUN_ID"],
        )
    elif args.command == "verify":
        info = verify_bundle(args.bundle, api.repository, args.tag, args.sha)
        if (
            args.manifest_sha256
            and digest(args.bundle / MANIFEST) != args.manifest_sha256
        ):
            raise ValueError(
                "Downloaded bundle differs from the draft's original manifest"
            )
        if args.run_id and info["run_id"] != args.run_id:
            raise ValueError("Downloaded bundle has an unexpected producing run")
    elif args.command == "publish":
        tag_version(args.tag)
        if not re.fullmatch(r"[1-9]\d*", args.artifact_id):
            raise ValueError("Invalid original artifact ID")
        print(publish(api, args.bundle, args.tag, args.sha, args.artifact_id))
    else:
        sync_readmes(api, args.root, args.branch)


if __name__ == "__main__":
    main()
