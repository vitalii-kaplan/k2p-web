from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, List
import zipfile


class ZipValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ZipLimits:
    max_files: int
    max_path_depth: int
    max_unpacked_bytes: int
    max_file_bytes: int


def _normalize_name(name: str) -> str:
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name


def _is_encrypted(info: zipfile.ZipInfo) -> bool:
    return bool(info.flag_bits & 0x1)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def _path_depth(name: str) -> int:
    return len(PurePosixPath(name).parts)


def _is_suspicious_name(name: str) -> bool:
    if not name:
        return True
    if "\x00" in name:
        return True
    if any(ord(ch) < 32 for ch in name):
        return True
    return False


def _is_unsafe_path(name: str) -> bool:
    if name.startswith("/"):
        return True
    if name.startswith("\\"):
        return True
    parts = PurePosixPath(name).parts
    if not parts:
        return True
    if parts[0].endswith(":"):
        return True
    if any(p in ("..", "") for p in parts):
        return True
    return False


def validate_zipfile(zf: zipfile.ZipFile, limits: ZipLimits) -> List[str]:
    infos = zf.infolist()
    if limits.max_files >= 0 and len(infos) > limits.max_files:
        raise ZipValidationError("zip_too_many_files", "Too many files in zip.")

    total = 0
    names: List[str] = []
    for info in infos:
        name = _normalize_name(info.filename)
        if _is_suspicious_name(name) or _is_unsafe_path(name):
            raise ZipValidationError("zip_path_unsafe", f"Unsafe path in zip: {info.filename}")
        if _is_encrypted(info):
            raise ZipValidationError("zip_encrypted", "Encrypted zip entries are not allowed.")
        if _is_symlink(info):
            raise ZipValidationError("zip_symlink", "Symlinks are not allowed in zip.")
        if limits.max_path_depth >= 0 and _path_depth(name) > limits.max_path_depth:
            raise ZipValidationError("zip_path_too_deep", "Zip entry path is too deep.")
        if limits.max_file_bytes >= 0 and info.file_size > limits.max_file_bytes:
            raise ZipValidationError("zip_entry_too_large", "Zip entry is too large.")
        total += info.file_size
        if limits.max_unpacked_bytes >= 0 and total > limits.max_unpacked_bytes:
            raise ZipValidationError("zip_bomb", "Zip exceeds maximum total uncompressed size.")
        names.append(name)

    return names


def safe_extract_zip(
    zip_path: Path,
    dest_dir: Path,
    *,
    limits: ZipLimits,
    ignore_prefixes: Iterable[str] | None = None,
) -> List[str]:
    ignore_prefixes = tuple(ignore_prefixes or ())
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()
    extracted: List[str] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        validate_zipfile(zf, limits)
        for info in zf.infolist():
            raw_name = _normalize_name(info.filename)
            if raw_name.startswith(ignore_prefixes):
                continue
            if raw_name.startswith("__MACOSX/") or "/__MACOSX/" in raw_name or Path(raw_name).name.startswith("._"):
                continue
            target = (dest_dir / raw_name).resolve()
            if target != dest_root and dest_root not in target.parents:
                raise ZipValidationError("zip_path_traversal", "Zip entry escapes target directory.")

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(chunk)
            extracted.append(raw_name)

    return extracted
