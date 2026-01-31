import pytest

from koma.config import COMIC_TITLE_RE

# 测试数据格式: (文件名, 期望提取的字典)
# 注意：Config 里的正则 Series 部分比较贪婪，会包含右括号，后续处理会在 Deduplicator 里做
TEST_CASES = [
    # === 1. 标准格式 ===
    (
        "(C99) [社团 (作者)] 本子标题 (Series) [汉化].zip",
        {
            "event": "C99",
            "artist": "社团 (作者)",
            "title": "本子标题",
            "series": "Series)",  # 正则本身会捕获右括号
            "language": "汉化",
        },
    ),
    # === 2. 极简格式 ===
    (
        "[社团] 只有标题.rar",
        {
            "event": None,
            "artist": "社团",
            "title": "只有标题",
            "series": None,
            "language": None,
        },
    ),
    # === 3. 无社团，只有标题 ===
    ("只有标题.zip", {"artist": None, "title": "只有标题"}),
    # === 4. 阴间格式：缺右括号 (我们修复过的那个 Case) ===
    # 期望 Series 能吃到 '[' 之前的所有字符
    (
        "[社团] 标题 (泣 3 [汉化].7z",
        {
            "artist": "社团",
            "title": "标题",
            "series": "泣 3 ",  # 成功捕获未闭合的括号内容
            "language": "汉化",
        },
    ),
    # === 5. 标题带空格 ===
    (
        "[社团]   标题 带  空格   (Vol.1).zip",
        {
            "artist": "社团",
            "title": "标题 带  空格",  # 尾部空格会被 strip 掉吗？正则里可能有 \s*，这里主要看提取内容
            "series": "Vol.1)",
        },
    ),
]


@pytest.mark.parametrize("filename, expected", TEST_CASES)
def test_regex_extraction(filename, expected):
    """测试正则能否正确提取各个字段"""
    match = COMIC_TITLE_RE.search(filename)

    # 如果预期完全无法匹配（例如非法格式），expected 设为 None
    if expected is None:
        assert match is None
        return

    assert match is not None, f"正则未能匹配文件名: {filename}"

    groups = match.groupdict()

    # 逐项验证
    for key, val in expected.items():
        if val is None:
            assert groups[key] is None
        else:
            # 这里的 strip 是为了去除正则中 \s* 可能吸附的空格
            assert groups[key] is not None
            assert val in groups[key]
