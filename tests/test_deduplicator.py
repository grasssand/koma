from koma.core.deduplicator import Deduplicator


def test_deduplicator_normalization(tmp_path):
    """测试核心：不同命名的文件能否被归为同一组"""

    # 1. 准备环境：创建几个空文件
    # 场景：同一个本子，三个不同版本
    files = [
        "[Group] Title (Vol.1).zip",  # 标准
        "(C99) [Group] Title (Vol.1) [CN].rar",  # 带展会和语言
        "[Group (Author)] Title (Vol.1).7z",  # 带作者名
    ]

    # 干扰项：完全不同的本子
    files.append("[Group] OtherTitle.zip")

    # 在临时目录创建这些文件
    input_dir = tmp_path / "downloads"
    input_dir.mkdir()
    for f in files:
        (input_dir / f).touch()

    # 2. 运行查重
    deduper = Deduplicator()
    # 传入包含这些文件的目录
    results = deduper.scan([input_dir])

    # 3. 验证结果
    # 应该只有 1 组重复结果
    assert len(results) == 1

    # 获取这组重复的 Key
    # 逻辑回顾：Artist(Group) + Title + Series(Vol.1)
    # Deduplicator 内部会做 lower() 和 strip()
    duplicate_keys = list(results.keys())
    target_key = duplicate_keys[0]

    print(f"生成的 Key 是: {target_key}")

    # 验证 Key 是否符合预期 (去掉了 Event, Lang, Author)
    assert "group" in target_key
    assert "title" in target_key
    assert "vol.1" in target_key

    # 验证这组里是否包含了那 3 个文件
    detected_paths = [item.path.name for item in results[target_key]]
    assert len(detected_paths) == 3
    assert "[Group] Title (Vol.1).zip" in detected_paths
    assert "(C99) [Group] Title (Vol.1) [CN].rar" in detected_paths
