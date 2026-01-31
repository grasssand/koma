import cv2
import numpy as np
from PIL import Image


def analyze_image(img_path) -> tuple[bool, bool]:
    """
    分析图片，判断是否为动图和灰度图
    返回 (is_anim, is_gray)
    """
    is_anim = False
    is_gray = False
    try:
        with Image.open(img_path) as img:
            is_anim = getattr(img, "is_animated", False)
            if is_anim:
                return True, False

        cv_img = cv2.imread(str(img_path))
        if cv_img is None:
            return False, False

        thumb = cv2.resize(cv_img, (64, 64), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(thumb, cv2.COLOR_BGR2HSV)
        s = hsv[:, :, 1]
        mean_sat = np.mean(s)
        is_gray = bool(mean_sat < 5.0)

        return is_anim, is_gray

    except Exception:
        return False, False
