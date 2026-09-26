"""Persist validated source images and resolve opaque IDs within their owner scope."""
import re
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


class ReferenceStore:
    def __init__(self, base):
        self.base = Path(base)
        self.root = self.base / 'assets' / 'generation_references'

    def scope(self, owner):
        value = str(owner or 'local')
        if not re.fullmatch(r'[\w-]+', value):
            raise ValueError('参考图用户归属无效')
        return self.root / value

    def save(self, raw, owner=None):
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError('图片不能超过 10 MB')
        try:
            with Image.open(BytesIO(raw)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 25000000:
                    raise ValueError('请使用不超过 2500 万像素的 JPG、PNG 或 WebP 图片')
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((2048, 2048))
                token = uuid.uuid4().hex
                path = self.scope(owner) / (token + '.png')
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(path)
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ValueError('无法读取图片，请重新选择 JPG、PNG 或 WebP 文件') from exc
        return self.describe(token, owner)

    def resolve(self, token, owner=None):
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{32}', token):
            raise ValueError('生成参考图无效，请重新上传')
        path = self.scope(owner) / (token + '.png')
        if not path.is_file():
            raise ValueError('生成参考图不存在或无权访问，请重新上传')
        return str(path)

    def describe(self, token, owner=None):
        path = Path(self.resolve(token, owner))
        return {'id': token, 'url': '/file/' + path.relative_to(self.base).as_posix()}
