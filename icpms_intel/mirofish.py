from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from urllib.parse import quote
from urllib.parse import urlsplit
from collections.abc import Mapping

import requests


class MiroFishConnectionError(RuntimeError):
    """Raised when a MiroFish project cannot be created safely."""


@dataclass(frozen=True)
class MiroFishProject:
    project_id: str
    task_id: str
    project_url: str


def configured_value(name: str, secrets: Mapping | None = None, default: str = "") -> str:
    """Read a MiroFish setting from process environment, then Streamlit secrets."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if secrets is not None:
        value = str(secrets.get(name, "") or "").strip()
        if value:
            return value
    return default


def default_connection_mode(
    app_url: str = "", configured_mode: str = "", api_url: str = ""
) -> str:
    """Choose a safe default based on explicit config and the app's public URL."""
    mode = configured_mode.strip().lower()
    if mode == "hosted":
        return "hosted"
    if api_url.strip().lower().startswith("https://"):
        return "hosted"
    hostname = (urlsplit(app_url).hostname or "").lower()
    if hostname and hostname not in {"localhost", "127.0.0.1", "::1"}:
        return "hosted"
    return "local"


def _base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise MiroFishConnectionError("MiroFish URL must start with http:// or https://")
    return base


def _is_non_public_host(hostname: str) -> bool:
    normalized = hostname.lower().rstrip(".")
    if normalized in {"localhost", "host.docker.internal"} or normalized.endswith(
        (".localhost", ".local", ".internal", ".lan", ".home")
    ):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _validate_api_url(value: str, mode: str) -> str:
    if not value.strip() and mode == "hosted":
        raise MiroFishConnectionError(
            "Configure MIROFISH_API_URL as a public HTTPS URL in Streamlit secrets or environment variables."
        )
    api = _base_url(value)
    if mode not in {"local", "hosted"}:
        raise MiroFishConnectionError("Choose Local or Hosted MiroFish connection mode.")
    parsed = urlsplit(api)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MiroFishConnectionError(
            "Do not put credentials or access parameters in the MiroFish URL; configure "
            "credentials with MIROFISH_API_TOKEN instead."
        )
    if mode == "hosted":
        if parsed.scheme != "https":
            raise MiroFishConnectionError(
                "Hosted mode requires a publicly reachable HTTPS MiroFish API URL. "
                "Set MIROFISH_API_URL in Streamlit secrets or environment variables."
            )
        hostname = (parsed.hostname or "").lower()
        if _is_non_public_host(hostname):
            raise MiroFishConnectionError(
                "Hosted Streamlit cannot reach localhost or host.docker.internal on your PC. "
                "Deploy MiroFish behind a public HTTPS endpoint and set MIROFISH_API_URL."
            )
    return api


def _validate_frontend_url(value: str, mode: str) -> str:
    frontend = _base_url(value)
    if mode == "hosted":
        parsed = urlsplit(frontend)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or _is_non_public_host(hostname)
        ):
            raise MiroFishConnectionError(
                "Hosted mode requires a public HTTPS MiroFish interface URL. "
                "Set MIROFISH_FRONTEND_URL in Streamlit secrets or environment variables."
            )
    return frontend


def _connection_error(api: str, mode: str, stage: str, exc: requests.RequestException) -> MiroFishConnectionError:
    hostname = urlsplit(api).hostname or "configured host"
    if isinstance(exc, requests.exceptions.SSLError):
        cause = "TLS certificate validation failed"
    elif isinstance(exc, requests.Timeout):
        cause = "the request timed out"
    else:
        cause = "DNS resolution, routing, firewall, or connection refusal failed"
    if mode == "hosted":
        guidance = (
            "Confirm this public HTTPS endpoint is online and reachable from Streamlit Community Cloud; "
            "a tunnel or hosted MiroFish deployment is required for a service on your PC."
        )
    else:
        guidance = (
            "Start the local MiroFish service and use http://localhost:5001 for native Streamlit, "
            "or http://host.docker.internal:5001 when Streamlit runs in Docker."
        )
    return MiroFishConnectionError(
        f"Could not reach the MiroFish API host '{hostname}' during its {stage} ({cause}). {guidance}"
    )


def _payload(response: requests.Response, action: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise MiroFishConnectionError(
            f"MiroFish returned an unreadable response while trying to {action}."
        ) from exc
    if not response.ok or not payload.get("success", False):
        message = payload.get("error") or f"HTTP {response.status_code}"
        raise MiroFishConnectionError(f"MiroFish could not {action}: {message}")
    return payload.get("data") or {}


def create_and_build_project(
    seed_document: str,
    simulation_requirement: str,
    api_url: str = "http://localhost:5001",
    frontend_url: str = "http://localhost:3000",
    project_name: str = "ICP-MS Potential Intelligence",
    timeout_seconds: int = 300,
    session=requests,
    mode: str = "local",
    api_token: str = "",
    access_client_id: str = "",
    access_client_secret: str = "",
) -> MiroFishProject:
    """Upload a seed, generate its ontology and start the graph build."""
    api = _validate_api_url(api_url, mode)
    frontend = _validate_frontend_url(frontend_url, mode)
    if not simulation_requirement.strip():
        raise MiroFishConnectionError("Enter a simulation question before sending the project.")

    if bool(access_client_id.strip()) != bool(access_client_secret.strip()):
        raise MiroFishConnectionError(
            "Configure both MIROFISH_ACCESS_CLIENT_ID and "
            "MIROFISH_ACCESS_CLIENT_SECRET, or leave both unset."
        )
    headers = {"Authorization": f"Bearer {api_token.strip()}"} if api_token.strip() else {}
    if access_client_id.strip():
        headers.update({
            "CF-Access-Client-Id": access_client_id.strip(),
            "CF-Access-Client-Secret": access_client_secret.strip(),
        })
    try:
        health = session.get(f"{api}/health", timeout=5, headers=headers)
    except requests.RequestException as exc:
        raise _connection_error(api, mode, "health check", exc) from exc
    if not health.ok:
        raise MiroFishConnectionError(
            f"MiroFish API host '{urlsplit(api).hostname}' responded to its health check "
            f"with HTTP {health.status_code}. Check the endpoint and any gateway credentials."
        )

    try:
        ontology_response = session.post(
            f"{api}/api/graph/ontology/generate",
            files={
                "files": (
                    "ICP-MS_MiroFish_Seed.md",
                    seed_document.encode("utf-8"),
                    "text/markdown",
                )
            },
            data={
                "simulation_requirement": simulation_requirement.strip(),
                "project_name": project_name.strip() or "ICP-MS Potential Intelligence",
                "additional_context": (
                    "Public-data decision support. Keep observed evidence, inference and "
                    "simulation output explicitly separated."
                ),
            },
            timeout=(10, timeout_seconds),
            headers=headers,
        )
    except requests.RequestException as exc:
        raise _connection_error(api, mode, "ontology request", exc) from exc
    try:
        ontology = _payload(ontology_response, "generate the project ontology")
        project_id = str(ontology.get("project_id", "")).strip()
        if not project_id:
            raise MiroFishConnectionError("MiroFish did not return a project ID.")

        build_response = session.post(
            f"{api}/api/graph/build",
            json={"project_id": project_id, "graph_name": project_name},
            timeout=(10, 30),
            headers=headers,
        )
    except requests.RequestException as exc:
        raise _connection_error(api, mode, "graph-build request", exc) from exc
    build = _payload(build_response, "start the graph build")
    return MiroFishProject(
        project_id=project_id,
        task_id=str(build.get("task_id", "")).strip(),
        project_url=f"{frontend}/process/{quote(project_id, safe='')}",
    )
