from pathlib import Path

import pytest

from tools.package_submission import (
    DEFAULT_FINAL_PPT,
    assert_public_member,
    inspect_presentation,
    presentation_for_status,
)


def test_private_and_credential_members_are_rejected():
    for name in (
        "source/evaluation/private_test/questions.json",
        "source/.local/project.json",
        "source/config/credentials.json",
        "source/config/client.key",
        "source/config/client.pem",
        "source/.env.local",
    ):
        with pytest.raises(ValueError):
            assert_public_member(name)

    assert_public_member("source/config/model.example.json")
    assert_public_member("source/config/.env.example")


def test_final_requires_existing_pptx(tmp_path):
    with pytest.raises(ValueError, match="最终PPT存在"):
        inspect_presentation(tmp_path / "missing.pptx", require_exists=True)

    wrong_suffix = tmp_path / "final.pdf"
    wrong_suffix.write_bytes(b"not a deck")
    with pytest.raises(ValueError, match=".pptx"):
        inspect_presentation(wrong_suffix, require_exists=True)


def test_final_requires_a_tracked_presentation(tmp_path):
    deck = tmp_path / "final.pptx"
    deck.write_bytes(b"fake pptx")
    with pytest.raises(ValueError, match="待打包提交跟踪"):
        inspect_presentation(deck, require_exists=True, require_tracked=True, root=tmp_path)


def test_final_candidate_and_final_status_validation():
    assert presentation_for_status("final_candidate", None) is None
    assert presentation_for_status("final", None)["path"] == DEFAULT_FINAL_PPT.as_posix()
    with pytest.raises(ValueError, match="未知包状态"):
        presentation_for_status("submitted", None)
    with pytest.raises(ValueError, match="最终PPT存在"):
        presentation_for_status("final_candidate", Path("missing.pptx"))
