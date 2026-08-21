from __future__ import annotations

from dataclasses import dataclass
import base64
import io
from pathlib import Path
from uuid import uuid4

from PIL import Image


class MediaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StoredMedia:
    relative_path: str
    absolute_path: Path
    content_type: str


_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
}


def media_root_for_db(db_path: str | Path, configured_dir: str = "media") -> Path:
    root = Path(configured_dir)
    if root.is_absolute():
        return root
    return Path(db_path).parent / root


def detect_image_type(data: bytes) -> tuple[str, str]:
    for signature, media_type in _IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return media_type
    raise MediaValidationError("Поддерживаются только JPEG и PNG")


def validate_image_bytes(data: bytes, *, max_bytes: int) -> tuple[str, str]:
    if not data:
        raise MediaValidationError("Файл пустой")
    if len(data) > max_bytes:
        raise MediaValidationError(f"Файл слишком большой: максимум {max_bytes // 1024 // 1024} МБ")
    return detect_image_type(data)


def store_image_bytes(
    data: bytes,
    *,
    media_root: str | Path,
    namespace: str,
    max_bytes: int,
) -> StoredMedia:
    extension, content_type = validate_image_bytes(data, max_bytes=max_bytes)
    safe_namespace = "/".join(part.strip("/.") for part in namespace.split("/") if part.strip("/."))
    relative_path = f"{safe_namespace}/{uuid4().hex}.{extension}" if safe_namespace else f"{uuid4().hex}.{extension}"
    root = Path(media_root)
    absolute_path = (root / relative_path).resolve()
    if root.resolve() not in absolute_path.parents:
        raise MediaValidationError("Некорректный путь файла")
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(data)
    return StoredMedia(relative_path=relative_path, absolute_path=absolute_path, content_type=content_type)


def resolve_media_path(media_root: str | Path, relative_path: str) -> Path:
    root = Path(media_root).resolve()
    absolute_path = (root / relative_path).resolve()
    if root not in absolute_path.parents and absolute_path != root:
        raise MediaValidationError("Некорректный путь файла")
    return absolute_path


def delete_media_file(media_root: str | Path, relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        path = resolve_media_path(media_root, relative_path)
    except MediaValidationError:
        return
    if path.exists() and path.is_file():
        path.unlink()


def image_data_url_for_llm(path: str | Path, *, max_side_px: int) -> str:
    image_path = Path(path)
    with Image.open(image_path) as image:
        image.thumbnail((max_side_px, max_side_px))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
