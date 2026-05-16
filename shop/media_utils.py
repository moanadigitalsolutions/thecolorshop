from __future__ import annotations

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


def should_convert_image(file_obj, media_type=''):
    resolved_type = (media_type or '').lower()
    file_name = getattr(file_obj, 'name', '') or ''
    extension = Path(file_name).suffix.lower()
    return resolved_type == 'image' and extension != '.webp'


def convert_image_file_to_webp(file_obj, output_name=None, quality=85, method=6):
    try:
        file_obj.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        image = Image.open(file_obj)
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError('Upload a valid image file.') from exc

    if getattr(image, 'is_animated', False):
        raise ValidationError('Animated image uploads are not supported.')

    if image.mode not in ('RGB', 'RGBA'):
        image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')

    output_buffer = BytesIO()
    image.save(output_buffer, format='WEBP', quality=quality, method=method)
    output_buffer.seek(0)

    source_name = output_name or getattr(file_obj, 'name', '') or 'image'
    target_name = f'{Path(source_name).stem}.webp'
    return ContentFile(output_buffer.read(), name=target_name)