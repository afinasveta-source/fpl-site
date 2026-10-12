"""Фото работ: проверка, хранение на сервере, просмотр.

Оригинал хранится как есть (orig/<sha256>.<ext>) — он нужен жюри и для архива и никому не отдаётся
наружу целиком. Для показа делается копия JPEG без метаданных (EXIF с геометкой телефона не уходит
дальше сервера), развёрнутая по EXIF: view/ — до 1600 px, thumb/ — до 480 px.
Одинаковые файлы хранятся один раз (имя — отпечаток содержимого).
"""
import hashlib
import io
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

FORMATS = {'JPEG': ('jpg', 'image/jpeg'), 'PNG': ('png', 'image/png'), 'WEBP': ('webp', 'image/webp')}
VIEW_PX, THUMB_PX = 1600, 480
MAX_PIXELS = 60_000_000          # больше — не фото с телефона, а попытка перегрузить сервер
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


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
        """Проверить и сохранить фото. Возвращает сведения для media_files."""
        try:
            with Image.open(io.BytesIO(data)) as probe:
                kind = probe.format
                probe.verify()
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                if kind not in FORMATS:
                    raise MediaError('unsupported_format')
                img = ImageOps.exif_transpose(img)
                width, height = img.size
                view = self._jpeg(img, VIEW_PX)
                thumb = self._jpeg(img, THUMB_PX)
        except MediaError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
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
    def _jpeg(img, limit):
        copy = img.copy()
        copy.thumbnail((limit, limit))
        if copy.mode not in ('RGB', 'L'):
            background = Image.new('RGB', copy.size, (255, 255, 255))
            rgba = copy.convert('RGBA')
            background.paste(rgba, mask=rgba.split()[-1])
            copy = background
        out = io.BytesIO()
        copy.save(out, 'JPEG', quality=85, optimize=True)   # без exif=... — метаданные не переносятся
        return out.getvalue()
