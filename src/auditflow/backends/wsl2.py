import re
import shlex
import shutil
from pathlib import Path

from auditflow.backends.base import (
    LIST_REMOTE,
    MAX_ARTIFACT_SIZE,
    READ_REMOTE,
    WRITE_REMOTE,
    BaseExecutionBackend,
    CmdResult,
    decode_png_names,
    exec_subprocess,
    remote_file,
    remote_operation,
    transport,
)
from auditflow.core.config import WslSettings

_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class Wsl2Backend(BaseExecutionBackend):
    name = "wsl2"

    def __init__(self, settings: WslSettings) -> None:
        if not settings.distro or settings.distro.startswith("-") or "\x00" in settings.distro:
            raise ValueError("invalid WSL distribution name")
        self.settings = settings
        remote_file(settings.workspace_root, "health.json")

    def _run(self, argv: list[str], *, stdin_bytes: bytes | None = None) -> bytes:
        return transport(
            ["wsl", "-d", self.settings.distro, "--exec", *argv],
            45,
            stdin_bytes=stdin_bytes,
        )

    def run_cmd(
        self,
        argv: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> CmdResult:
        if not argv:
            raise ValueError("command argv cannot be empty")
        parts: list[str] = []
        if cwd is not None:
            parts.append(f"cd -- {shlex.quote(str(cwd))}")
        if env:
            for key, value in env.items():
                if not _ENV_KEY.fullmatch(key):
                    raise ValueError(f"invalid environment variable name: {key!r}")
                parts.append(f"export {key}={shlex.quote(value)}")
        parts.append(f"exec {shlex.join(argv)}")
        cmd = [
            "wsl",
            "-d",
            self.settings.distro,
            "--exec",
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            " && ".join(parts),
        ]
        return exec_subprocess(cmd, timeout=timeout)

    def read_file(self, path: str) -> bytes:
        return remote_operation(self._run, self.settings.workspace_root, path, READ_REMOTE)

    def push_file(self, local_path: Path, remote_path: str) -> None:
        data = local_path.read_bytes()
        if len(data) > MAX_ARTIFACT_SIZE:
            raise ValueError("artifact exceeds the size limit")
        remote_file(self.settings.workspace_root, remote_path)
        self._run(
            [
                "bash",
                "--noprofile",
                "--norc",
                "-c",
                WRITE_REMOTE,
                "--",
                self.settings.workspace_root,
                remote_path,
            ],
            stdin_bytes=data,
        )

    def list_png(self, path: str) -> list[str]:
        return decode_png_names(
            remote_operation(self._run, self.settings.workspace_root, path, LIST_REMOTE)
        )

    def check_health(self) -> tuple[bool, str]:
        if shutil.which("wsl") is None:
            return False, "WSL launcher not found in PATH"
        return True, f"WSL2 ready (distro={self.settings.distro}, root={self.settings.workspace_root})"
