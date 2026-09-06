from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-image.yml"
DOCKERFILE = ROOT / "Dockerfile"


def test_release_publication_is_main_only_and_does_not_deploy() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "- main" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert "packages: write" in workflow
    assert "sha-$GITHUB_SHA" in workflow
    assert "@sha256:" not in workflow
    assert ":latest" not in workflow
    assert not re.search(r"\b(ssh|scp|rsync)\b", workflow)


def test_release_actions_are_pinned_and_use_node24() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*- uses:\s+(\S+)", workflow, flags=re.MULTILINE)

    assert uses == [
        "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
    ]
    assert "Node.js 24" in workflow


def test_release_image_records_oci_source_and_revision() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "org.opencontainers.image.source=$SOURCE_URL" in dockerfile
    assert "org.opencontainers.image.revision=$VCS_REF" in dockerfile
    assert 'VCS_REF=$GITHUB_SHA' in WORKFLOW.read_text(encoding="utf-8")
