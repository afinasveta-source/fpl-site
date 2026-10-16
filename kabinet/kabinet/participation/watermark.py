"""Водяной знак FPL на фото работ, которые видят другие люди (16.10): галерея тура, исходник эстафеты, лента данных
(соцсети). Автор, организатор, модератор, судья и разбор — фото без знака. Оригинал и сохранённые копии не меняются:
копия со знаком делается при первом показе и кладётся рядом (wm1/view/…, wm1/thumb/…); поменяли знак — новая папка wm2/.

Знак — белый логотип FPL с мягкой тенью в правом нижнем углу, ширина ~16 % короткой стороны, непрозрачность 78 %.
"""
import io
import threading
from pathlib import Path

from PIL import Image, ImageFilter

VERSION = 'wm1'
LOGO = Path(__file__).resolve().parent.parent / 'static' / 'assets' / 'fpl-wm.png'   # маска (только прозрачность)
FRAC, OPACITY = 0.16, 0.78
_GATE = threading.BoundedSemaphore(2)   # память службы ограничена: не больше двух наложений сразу
_mask = None


def _logo():
    global _mask
    if _mask is None:
        with Image.open(LOGO) as m:
            _mask = m.convert('L').copy()
    return _mask


def apply(img):
    img = img.convert('RGB')
    w, h = img.size
    logo = _logo()
    lw = max(40, round(min(w, h) * FRAC))
    a = logo.resize((lw, max(1, round(logo.height * lw / logo.width))), Image.Resampling.LANCZOS)
    pad = max(6, lw // 8)
    size = (a.width + 2 * pad, a.height + 2 * pad)
    shadow = Image.new('L', size, 0)
    shadow.paste(a, (pad, pad))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, lw // 30))).point(lambda v: int(v * 0.55 * OPACITY))
    fg = Image.new('L', size, 0)
    fg.paste(a, (pad, pad))
    fg = fg.point(lambda v: int(v * OPACITY))
    m = max(8, round(min(w, h) * 0.025))
    x, y = w - size[0] - m + pad, h - size[1] - m + pad
    img.paste((0, 0, 0), (x + 1, y + 2), shadow)
    img.paste((255, 255, 255), (x, y), fg)
    return img


def path_for(store, key):
    """Файл копии со знаком для сохранённой копии key (view/… или thumb/…); делает её при первом обращении."""
    src = store.path(key)
    wkey = f"{VERSION}/{(key or '').split('#', 1)[0]}"
    target = store.path(wkey)
    if target.is_file():
        return target
    with _GATE:
        if target.is_file():
            return target
        with Image.open(src) as im:
            out = apply(im)
        buf = io.BytesIO()
        out.save(buf, 'JPEG', quality=85, optimize=True)
        store._write(wkey, buf.getvalue())
    return target
