"""Фото работ: проверка, хранение на сервере, просмотр.

Оригинал хранится как есть (orig/<sha256>.<ext>) — он нужен жюри и для архива и никому не отдаётся
наружу целиком. Для показа делается копия JPEG без метаданных (EXIF с геометкой телефона не уходит
дальше сервера), развёрнутая по EXIF: view/ — до 1600 px, thumb/ — до 480 px.
Одинаковые файлы хранятся один раз (имя — отпечаток содержимого).
"""
import hashlib
import io
import math
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

FORMATS = {'JPEG': ('jpg', 'image/jpeg'), 'PNG': ('png', 'image/png'), 'WEBP': ('webp', 'image/webp')}
VIEW_PX, THUMB_PX = 1600, 480
MAX_PIXELS = 120_000_000         # телефоны дают до ~108 Мп; больше — не фото, а попытка перегрузить сервер
MAX_PIXELS_OTHER = 12_000_000    # PNG и WebP декодируются целиком: держим память службы в пределах
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _fit(size, limit):
    w, h = size
    k = limit / max(w, h)
    return max(1, round(w * k)), max(1, round(h * k))


class MediaError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class MediaStore:
    def __init__(self, root, min_free_mb=1024):
        self.root = Path(root)
        self.min_free = min_free_mb * 1024 * 1024

    def path(self, key):
        """Путь к файлу по ключу записи. Ключ оригинала — «путь#id записи»: файл общий у одинаковых фото."""
        key = (key or '').split('#', 1)[0]
        if not key or '..' in key or key.startswith('/') or not key.replace('/', '').replace('.', '').isalnum():
            raise MediaError('bad_key')
        return self.root / key

    def _write(self, key, data):
        target = self.path(key)
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.chmod(tmp, 0o640)
        os.replace(tmp, target)

    def free_ok(self, incoming):
        self.root.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(self.root).free - incoming * 4 > self.min_free

    def save_image(self, data):
        """Проверить и сохранить фото. Возвращает сведения для media_files.

        Память ограничена (служба — до 350 МБ): размер в пикселях проверяется по заголовку до декодирования,
        JPEG декодируется сразу в уменьшенном виде (draft), уменьшение и поворот — без лишних полных копий.
        """
        try:
            with Image.open(io.BytesIO(data)) as probe:
                kind = probe.format
                raw_w, raw_h = width, height = probe.size
                if probe.getexif().get(0x0112) in (5, 6, 7, 8):   # снято «боком»: показываем повёрнутым
                    width, height = height, width
                probe.verify()
            if kind not in FORMATS:
                raise MediaError('unsupported_format')
            if width * height > (MAX_PIXELS if kind == 'JPEG' else MAX_PIXELS_OTHER):
                raise MediaError('too_many_pixels')
            with Image.open(io.BytesIO(data)) as img:
                if kind == 'JPEG':
                    # Декодирование сразу в 1/2–1/8 масштаба: просим размер, пропорциональный фото, — тогда большая
                    # сторона остаётся не меньше 1600 px. (Квадрат 1600×1600 у фото 4:3 не давал уменьшения вовсе:
                    # 12 Мп декодировались целиком — 0,5 с и 36 МБ на фото; нагрузочный тест 13.10.)
                    k = VIEW_PX / max(raw_w, raw_h)
                    if k < 1:
                        img.draft('RGB', (math.ceil(raw_w * k), math.ceil(raw_h * k)))
                img.load()
                img.thumbnail((VIEW_PX * 2, VIEW_PX * 2))
                img = ImageOps.exif_transpose(img) or img
                shown = self._fit_image(img, VIEW_PX)
                view = self._encode(shown)
                thumb = self._encode(self._fit_image(shown, THUMB_PX))   # маленькая копия — из уменьшенной, быстрее
        except MediaError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError,
                SyntaxError, ValueError, MemoryError):
            raise MediaError('not_an_image') from None
        if not self.free_ok(len(data) + len(view) + len(thumb)):
            raise MediaError('storage_full')
        digest = hashlib.sha256(data).hexdigest()
        ext, mime = FORMATS[kind]
        keys = {'orig': f'orig/{digest[:2]}/{digest}.{ext}', 'view': f'view/{digest[:2]}/{digest}.jpg',
                'thumb': f'thumb/{digest[:2]}/{digest}.jpg'}
        self._write(keys['orig'], data)
        self._write(keys['view'], view)
        self._write(keys['thumb'], thumb)
        return {'sha256': digest, 'mime_type': mime, 'size_bytes': len(data), 'width': width, 'height': height,
                'storage_key': keys['orig'], 'optimized_storage_key': keys['view'], 'thumbnail_storage_key': keys['thumb']}

    @staticmethod
    def _fit_image(img, limit):
        return img if max(img.size) <= limit else img.resize(_fit(img.size, limit), Image.Resampling.LANCZOS)

    @staticmethod
    def _encode(copy):
        if copy.mode not in ('RGB', 'L'):
            background = Image.new('RGB', copy.size, (255, 255, 255))
            rgba = copy.convert('RGBA')
            background.paste(rgba, mask=rgba.split()[-1])
            copy = background
        out = io.BytesIO()
        copy.save(out, 'JPEG', quality=85, optimize=True)   # без exif=... — метаданные не переносятся
        return out.getvalue()
