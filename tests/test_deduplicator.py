from koma.core.deduplicator import Deduplicator


def test_normalization(tmp_path, ext_config, dedupe_config):
    """测试核心：不同命名的文件能否被归为同一组"""
    files = [
        "[Group] Title (Vol.1).zip",  # 标准
        "(C99) [Group] Title (Vol.1) [CN].rar",  # 带展会和语言
        "[Group (Author)] Title (Vol.1).7z",  # 带作者名
    ]
    files.append("[Group] OtherTitle.zip")

    input_dir = tmp_path / "downloads"
    input_dir.mkdir()
    for f in files:
        (input_dir / f).touch()

    deduper = Deduplicator(ext_config, dedupe_config)
    results = deduper.run([input_dir])

    assert len(results) == 1

    duplicate_keys = list(results.keys())
    target_key = duplicate_keys[0]

    assert "group" in target_key
    assert "title" in target_key
    assert "vol.1" in target_key

    detected_paths = [item.path.name for item in results[target_key]]
    assert len(detected_paths) == 3
    assert "[Group] Title (Vol.1).zip" in detected_paths
    assert "(C99) [Group] Title (Vol.1) [CN].rar" in detected_paths
