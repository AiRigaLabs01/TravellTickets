from pathlib import Path


def test_ci_uses_node24_actions_and_blocking_type_check():
    workflow = Path(".github/workflows/ci.yml").read_text()
    assert "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert "continue-on-error" not in workflow
