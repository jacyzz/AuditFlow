import socket
import time
from ipaddress import ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import HttpUrl

from auditflow.backends.base import BaseExecutionBackend
from auditflow.core.config import DockerSettings
from auditflow.core.schemas import DeployAttempt, DeployLog, Verify, WebStep

_ISOLATED_NETWORKS = tuple(
    ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )
)


def validate_isolated_endpoint(url: str, settings: DockerSettings) -> str:
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("expected an isolated HTTP(S) URL without credentials or fragment")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if settings.enforce_port_range:
        low, high = settings.port_range
        if not low <= port <= high:
            raise ValueError("recorded endpoint port falls outside the configured isolation range")

    hosts = {item.casefold() for item in settings.allowed_target_hosts}
    if hostname == "localhost" and hostname in hosts:
        return url
    try:
        address = ip_address(hostname)
    except ValueError:
        raise ValueError("use localhost or a literal isolated IP address") from None
    if getattr(address, "scope_id", None):
        raise ValueError("scoped IP addresses are unsupported")
    address = getattr(address, "ipv4_mapped", None) or address
    if not any(address in network for network in _ISOLATED_NETWORKS):
        raise ValueError("endpoint is outside private and loopback address space")
    if str(address) not in hosts and not any(
        address in ip_network(item) for item in settings.allowed_target_cidrs
    ):
        raise ValueError("endpoint is outside the configured isolation allowlist")
    return url


def validate_environment_records(
    settings: DockerSettings, deploy: DeployLog | None = None, verify: Verify | None = None,
) -> None:
    if deploy is not None and deploy.exposed_base_url is not None:
        validate_isolated_endpoint(str(deploy.exposed_base_url), settings)
    if verify is not None:
        for step in verify.steps:
            if isinstance(step, WebStep):
                validate_isolated_endpoint(str(step.url), settings)


def suggest_local_port(settings: DockerSettings) -> int:
    """Return a currently free loopback port. The check leaves the port unreserved."""
    low, high = settings.port_range
    for port in range(low, high + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise ValueError("no free loopback port in the configured range")


def build_docker_env(
    settings: DockerSettings, extra_env: dict[str, str] | None = None
) -> dict[str, str]:
    """Build proxy and optional Burp upstream environment variables for isolated runs."""
    env: dict[str, str] = {}
    if settings.http_proxy:
        env["HTTP_PROXY"] = settings.http_proxy
        env["http_proxy"] = settings.http_proxy
    if settings.https_proxy:
        env["HTTPS_PROXY"] = settings.https_proxy
        env["https_proxy"] = settings.https_proxy
    if settings.no_proxy:
        env["NO_PROXY"] = settings.no_proxy
        env["no_proxy"] = settings.no_proxy
    if settings.burp_upstream_proxy:
        env["AUDITFLOW_BURP_UPSTREAM_PROXY"] = settings.burp_upstream_proxy
    if extra_env:
        env.update(extra_env)
    return env


def http_client_for_verify(
    settings: DockerSettings,
    *,
    timeout: float = 15.0,
    follow_redirects: bool = False,
    verify_tls: bool = True,
) -> httpx.Client:
    """Create an httpx.Client restricted to isolated targets, optionally routing through Burp."""

    def _guard_request(request: httpx.Request) -> None:
        validate_isolated_endpoint(str(request.url), settings)

    proxy = settings.burp_upstream_proxy or None
    # When routing through a local Burp proxy, TLS interception commonly uses Burp's local CA.
    tls_verify = False if proxy else verify_tls
    return httpx.Client(
        proxy=proxy,
        timeout=timeout,
        follow_redirects=follow_redirects,
        verify=tls_verify,
        trust_env=False,
        event_hooks={"request": [_guard_request]},
    )


def teardown_docker_compose(
    backend: BaseExecutionBackend,
    compose_dir: str | Path,
    *,
    compose_file: str | None = None,
    timeout: int = 120,
) -> bool:
    """Stop and clean up containers for an isolated verification workspace."""
    argv = ["docker", "compose"]
    if compose_file:
        argv.extend(["-f", compose_file])
    argv.extend(["down", "--remove-orphans"])
    return backend.run_cmd(argv, cwd=compose_dir, timeout=timeout).ok


def run_docker_compose_deploy(
    backend: BaseExecutionBackend,
    compose_dir: str | Path,
    candidate_id: str,
    settings: DockerSettings,
    *,
    exposed_base_url: str | None = None,
    healthcheck_url: str | None = None,
    compose_file: str | None = None,
    precondition_overrides: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    health_client: httpx.Client | None = None,
) -> DeployLog:
    """Deploy an official docker-compose stack with proxy injection and fail-fast retry cap."""
    if exposed_base_url:
        validate_isolated_endpoint(exposed_base_url, settings)
    if healthcheck_url:
        validate_isolated_endpoint(healthcheck_url, settings)

    argv = ["docker", "compose"]
    if compose_file:
        argv.extend(["-f", compose_file])
    argv.extend(["up", "-d"])
    deploy_env = build_docker_env(settings, extra_env)
    proxy_url = HttpUrl(settings.https_proxy or settings.http_proxy) if (
        settings.https_proxy or settings.http_proxy
    ) else None

    max_attempts = max(1, settings.max_retries + 1)
    attempts: list[DeployAttempt] = []
    ready = False
    for index in range(1, max_attempts + 1):
        started = time.monotonic()
        res = backend.run_cmd(
            argv, cwd=compose_dir, env=deploy_env, timeout=settings.startup_timeout_sec
        )
        duration = round(time.monotonic() - started, 3)
        if res.timed_out:
            attempts.append(
                DeployAttempt(
                    attempt=index,
                    status="timeout",
                    duration_sec=duration,
                    healthcheck=None,
                    error_summary=f"docker compose up timed out after {settings.startup_timeout_sec}s",
                )
            )
            continue
        if not res.ok:
            summary = (res.stderr or res.stdout or f"exit code {res.returncode}").strip()[-500:]
            attempts.append(
                DeployAttempt(
                    attempt=index,
                    status="failed",
                    duration_sec=duration,
                    healthcheck=None,
                    error_summary=summary,
                )
            )
            continue
        health_note = "docker compose up -d succeeded"
        if healthcheck_url:
            try:
                if health_client is not None:
                    resp = health_client.get(healthcheck_url)
                else:
                    with http_client_for_verify(settings, timeout=10.0) as client:
                        resp = client.get(healthcheck_url)
                health_note = f"GET {healthcheck_url} -> {resp.status_code}"
                if resp.status_code >= 500:
                    attempts.append(
                        DeployAttempt(
                            attempt=index,
                            status="failed",
                            duration_sec=round(time.monotonic() - started, 3),
                            healthcheck=health_note,
                            error_summary=f"healthcheck returned HTTP {resp.status_code}",
                        )
                    )
                    continue
            except httpx.HTTPError as exc:
                attempts.append(
                    DeployAttempt(
                        attempt=index,
                        status="failed",
                        duration_sec=round(time.monotonic() - started, 3),
                        healthcheck=f"GET {healthcheck_url} -> error",
                        error_summary=str(exc)[:400],
                    )
                )
                continue
        attempts.append(
            DeployAttempt(
                attempt=index,
                status="success",
                duration_sec=round(time.monotonic() - started, 3),
                healthcheck=health_note,
                error_summary=None,
            )
        )
        ready = True
        break

    teardown_done = False
    if not ready:
        teardown_done = teardown_docker_compose(backend, compose_dir, compose_file=compose_file)

    return DeployLog(
        candidate_id=candidate_id,
        backend=backend.name,
        deploy_mode="docker-compose",
        deploy_commands=[" ".join(argv)],
        proxy_used=proxy_url,
        exposed_base_url=HttpUrl(exposed_base_url) if exposed_base_url else None,
        precondition_overrides=list(precondition_overrides or []),
        attempts=attempts,
        final_status="READY" if ready else "NEEDS_HUMAN_ENV",
        teardown_completed=teardown_done,
    )
