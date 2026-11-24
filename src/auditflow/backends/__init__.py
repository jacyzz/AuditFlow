from auditflow.backends.base import BaseExecutionBackend
from auditflow.backends.local import LocalBackend
from auditflow.backends.ssh_ubuntu import SshUbuntuBackend
from auditflow.backends.wsl2 import Wsl2Backend
from auditflow.core.config import Backends


def get_backend(name: str, settings: Backends) -> BaseExecutionBackend:
    if name == "local":
        return LocalBackend()
    if name == "ssh-ubuntu" and settings.ssh_ubuntu is not None:
        return SshUbuntuBackend(settings.ssh_ubuntu)
    if name == "wsl2" and settings.wsl2 is not None:
        return Wsl2Backend(settings.wsl2)
    raise ValueError(f"backend unavailable or unconfigured: {name}")
