from pathlib import Path

import pytest

from koma.core.file_safety import atomic_output, move_no_replace, validate_prefix


def test_atomic_output_replaces_only_after_complete_write(tmp_path: Path):
    target = tmp_path / "result.zip"
    target.write_bytes(b"old")

    with pytest.raises(RuntimeError), atomic_output(target) as staged:
        assert staged.suffix == ".zip"
        staged.write_bytes(b"partial")
        raise RuntimeError("encoding failed")

    assert target.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [target]

    with atomic_output(target) as staged:
        staged.write_bytes(b"complete")
    assert target.read_bytes() == b"complete"
    assert list(tmp_path.iterdir()) == [target]


def test_move_no_replace_preserves_existing_target_and_source(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"source")
    target.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        move_no_replace(source, target)

    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"existing"


def test_move_no_replace_publishes_source_without_overwrite(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"data")

    move_no_replace(source, target)

    assert not source.exists()
    assert target.read_bytes() == b"data"


@pytest.mark.parametrize(
    "prefix", ["../", "..\\", "/absolute", "C:\\outside", "bad:name"]
)
def test_validate_prefix_rejects_path_components(prefix: str):
    with pytest.raises(ValueError):
        validate_prefix(prefix)


def test_validate_prefix_accepts_normal_unicode_text():
    validate_prefix("第 1 册-作者_")
