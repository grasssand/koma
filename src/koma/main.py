from tkinterdnd2 import TkinterDnD

from koma.ui import KomaGUI
from koma.utils import logger


def main():
    # 启动 GUI
    try:
        root = TkinterDnD.Tk()
        KomaGUI(root)
        root.mainloop()

    except Exception as e:
        logger.critical(f"App crashed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
