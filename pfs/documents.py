"""Hash real files. Do not accept a 64-hex caption as a document."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class DocumentBinding:
    path: Optional[str]
    sha256: Optional[str]
    bound: bool


def bind_file(path: Optional[str]) -> DocumentBinding:
    if not path:
        return DocumentBinding(path=None, sha256=None, bound=False)
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return DocumentBinding(path=str(p), sha256=None, bound=False)
    return DocumentBinding(path=str(p), sha256=sha256_file(p), bound=True)
