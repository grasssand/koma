import tkinter.font as tkfont


def get_sans_font():
    """获取系统无衬线字体名称"""
    available_fonts = set(tkfont.families())
    preferred_fonts = [
        "Noto Sans CJK SC",
        "Source Han Sans CN",
        "微软雅黑",  # Windows
        "Helvetica",  # macOS
        "Noto Sans",
        "Liberation Sans",
    ]
    for font in preferred_fonts:
        if font in available_fonts:
            return font

    return "TkDefaultFont"


def get_monospace_font():
    """获取系统等宽字体名称"""
    available_fonts = set(tkfont.families())
    preferred_fonts = [
        "Maple Mono NF CN",  # 等宽中文字体
        "DejaVu Sans Mono",
        "Source Code Pro",
        "Consolas",  # Windows
        "Menlo",  # macOS
        "Liberation Mono",
        "Courier New",
    ]
    for font in preferred_fonts:
        if font in available_fonts:
            return font

    return "TkFixedFont"
