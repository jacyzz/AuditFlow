import os
from pathlib import Path

from auditflow.backends.base import (
    MAX_ARTIFACT_SIZE,
    BaseExecutionBackend,
    CmdResult,
    exec_subprocess,
)
from auditflow.core.paths import atomic_write, contained_path, relative_path


class LocalBackend(BaseExecutionBackend):
    name = "local"

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()

    def run_cmd(
        self,
        argv: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> CmdResult:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        work_dir = Path(cwd) if cwd is not None else self.root
        return exec_subprocess(argv, cwd=work_dir, env=merged_env, timeout=timeout)

    def read_file(self, path: str) -> bytes:
        with contained_path(self.root, path).open("rb") as handle:
            data = handle.read(MAX_ARTIFACT_SIZE + 1)
        if len(data) > MAX_ARTIFACT_SIZE:
            raise ValueError("artifact exceeds the size limit")
        return data

    def push_file(self, local_path: Path, remote_path: str) -> None:
        data = local_path.read_bytes()
        if len(data) > MAX_ARTIFACT_SIZE:
            raise ValueError("artifact exceeds the size limit")
        atomic_write(contained_path(self.root, remote_path), data)

    def check_health(self) -> tuple[bool, str]:
        return self.root.is_dir(), f"local execution root: {self.root}"

    def list_png(self, path: str) -> list[str]:
        directory = contained_path(self.root, path)
        return sorted(
            relative_path(entry.name)
            for entry in directory.iterdir()
            if not entry.is_symlink() and entry.is_file() and entry.suffix == ".png"
        )
