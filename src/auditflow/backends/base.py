import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from auditflow.core.paths import atomic_write, relative_path

MAX_ARTIFACT_SIZE = 32 * 1024 * 1024


@dataclass(slots=True)
class CmdResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class BaseExecutionBackend(ABC):
    name: str

    @abstractmethod
    def run_cmd(
        self,
        argv: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> CmdResult:
        """Execute a command argument vector in this backend."""

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read a file identified relative to the configured artifact root."""

    @abstractmethod
    def push_file(self, local_path: Path, remote_path: str) -> None:
        """Write a local file into the backend workspace root."""

    def pull_file(self, remote_path: str, local_path: Path) -> None:
        atomic_write(local_path, self.read_file(remote_path))

    @abstractmethod
    def list_png(self, path: str) -> list[str]:
        """List the PNG names directly in the requested artifact directory."""

    @abstractmethod
    def check_health(self) -> tuple[bool, str]:
        """Report availability of the execution backend."""


def remote_file(root: str, path: str) -> str:
    directory = PurePosixPath(root)
    if not directory.is_absolute() or ".." in directory.parts or "\x00" in root:
        raise ValueError("configure an absolute Linux workspace root")
    return str(directory / relative_path(path))


_REMOTE_PATH = """
root=$(realpath -e -- "$1") || exit 46
[ -d "$root" ] || exit 46
requested="$root/$2"
if [ ! -e "$requested" ] && [ ! -L "$requested" ]; then exit 44; fi
path=$(realpath -e -- "$requested") || exit 46
case "$path" in "$root"/*) ;; *) exit 46 ;; esac
"""
READ_REMOTE = _REMOTE_PATH + """
[ -f "$path" ] || exit 46
head -c 33554433 -- "$path"
"""
LIST_REMOTE = _REMOTE_PATH + """
[ -d "$path" ] || exit 46
find "$path" -maxdepth 1 -type f -name '*.png' -printf '%f\\0'
"""
WRITE_REMOTE = """
mkdir -p -- "$1" || exit 46
root=$(realpath -e -- "$1") || exit 46
target="$root/$2"
parent=$(dirname -- "$target")
mkdir -p -- "$parent" || exit 46
real_parent=$(realpath -e -- "$parent") || exit 46
case "$real_parent" in "$root"|"$root"/*) ;; *) exit 46 ;; esac
tmp=$(mktemp "$real_parent/.auditflow-tmp.XXXXXX") || exit 46
cat > "$tmp" || { rm -f -- "$tmp"; exit 46; }
mv -f -- "$tmp" "$target"
"""


def remote_operation(
    run: Callable[[list[str]], bytes], root: str, path: str, script: str
) -> bytes:
    remote_file(root, path)
    return run(["bash", "--noprofile", "--norc", "-c", script, "--", root, path])


def decode_png_names(data: bytes) -> list[str]:
    names = data.decode("utf-8").split("\0")
    return sorted(
        name for name in names if name and "/" not in relative_path(name) and name.endswith(".png")
    )


def transport(argv: list[str], timeout: int, *, stdin_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            argv,
            input=stdin_bytes,
            stdin=None if stdin_bytes is not None else subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("artifact transport timed out") from exc
    if result.returncode == 44:
        raise FileNotFoundError("remote artifact is missing")
    if result.returncode:
        raise OSError(f"artifact transport exited with status {result.returncode}")
    if len(result.stdout) > MAX_ARTIFACT_SIZE:
        raise ValueError("artifact exceeds the size limit")
    return result.stdout


def exec_subprocess(
    argv: list[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> CmdResult:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return CmdResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CmdResult(
            returncode=124,
            stdout=exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or ""),
            stderr=exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "command timed out"),
            timed_out=True,
        )
    except OSError as exc:
        return CmdResult(returncode=127, stderr=str(exc))
