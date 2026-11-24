import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _is_reserved_name(name: str) -> bool:
    stem = name.split(".", 1)[0].rstrip(" ").upper()
    if stem in _WINDOWS_RESERVED:
        return True
    isreserved = getattr(os.path, "isreserved", None)
    if callable(isreserved):
        return bool(isreserved(name))
    return PureWindowsPath(name).is_reserved()


def artifact_id(value: str) -> str:
    if not _ID.fullmatch(value) or value.endswith(".") or _is_reserved_name(value):
        raise ValueError(f"invalid artifact identifier: {value!r}")
    return value


def relative_path(value: str) -> str:
    parts = value.split("/")
    if (
        not value
        or any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in parts)
        or any(_is_reserved_name(part) for part in parts)
        or any(char in value for char in '\\:*?"<>|')
        or any(ord(char) < 32 for char in value)
        or PurePosixPath(value).is_absolute()
    ):
        raise ValueError(f"expected a portable relative path: {value!r}")
    return value


def contained_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative_path(relative)).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes the workspace: {relative!r}")
    return path


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def workspace_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".dispatch.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f"workspace is already being updated: {directory.name}") from exc
    os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
