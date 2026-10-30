import re
from pathlib import Path

from .models import Resource


def remove_resource(private_root: Path, resource: Resource) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", resource.id):
        raise OSError("资源标识无效，拒绝删除")
    root = private_root.resolve()
    folder, extension = ("audio", "wav") if resource.kind == "audio" else ("exports", "html")
    target = private_root / folder / f"{resource.id}.{extension}"
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise OSError("资源路径越界，拒绝删除")
    target.unlink(missing_ok=True)
