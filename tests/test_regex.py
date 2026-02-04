import re

import pytest

from koma.config import DEFAULT_COMIC_REGEX

TEST_CASES = [
    (
        "(C99) [社团 (作者)] 本子标题 (Series) [汉化].zip",
        {
            "event": "C99",
            "artist": "社团 (作者)",
            "title": "本子标题",
            "series": "Series)",
            "language": "汉化",
        },
    ),
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
    ("只有标题.zip", {"artist": None, "title": "只有标题"}),
    (
        "[社团] 标题 (泣 3 [汉化].7z",
        {
            "artist": "社团",
            "title": "标题",
            "series": "泣 3 ",
            "language": "汉化",
        },
    ),
    (
        "[社团]   标题 带  空格   (Vol.1).zip",
        {
            "artist": "社团",
            "title": "标题 带  空格",
            "series": "Vol.1)",
        },
    ),
]


@pytest.mark.parametrize("filename, expected", TEST_CASES)
def test_regex_extraction(filename, expected):
    """测试正则能否正确提取各个字段"""
    regex = re.compile(DEFAULT_COMIC_REGEX)
    match = regex.search(filename)

    if expected is None:
        assert match is None
        return

    assert match is not None, f"正则未能匹配文件名: {filename}"

    groups = match.groupdict()

    for key, val in expected.items():
        if val is None:
            assert groups[key] is None
        else:
            assert groups[key] is not None
            assert val in groups[key]
