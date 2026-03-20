import argparse
import pathlib
import re


def normalize_tag(tag: str) -> str:
    value = tag.strip()
    if value.startswith("v"):
        value = value[1:]
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"Unsupported tag format: {tag}. Expected vX.Y.Z or X.Y.Z")
    return value


def update_readme(readme_path: pathlib.Path, version: str) -> None:
    text = readme_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'https://github\.com/ShabbyGayBar/StateMerger/releases/download/v[0-9]+\.[0-9]+\.[0-9]+/vic3_state_merger-[0-9]+\.[0-9]+\.[0-9]+-py3-none-any\.whl'
    )
    new_link = (
        f"https://github.com/ShabbyGayBar/StateMerger/releases/download/v{version}/"
        f"vic3_state_merger-{version}-py3-none-any.whl"
    )
    updated, replacements = pattern.subn(new_link, text)
    if replacements == 0:
        raise RuntimeError(f"No release wheel link found in {readme_path}")
    readme_path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync README release links from a git tag"
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="Release tag in vX.Y.Z or X.Y.Z format",
    )
    args = parser.parse_args()

    version = normalize_tag(args.tag)
    root = pathlib.Path(__file__).resolve().parents[1]

    update_readme(root / "README.md", version)
    update_readme(root / "docs" / "README_zh-CN.md", version)

    print(f"Synced README links to v{version}")


if __name__ == "__main__":
    main()
