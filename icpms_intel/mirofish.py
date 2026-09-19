from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import requests


class MiroFishConnectionError(RuntimeError):
    """Raised when a MiroFish project cannot be created safely."""


@dataclass(frozen=True)
class MiroFishProject:
    project_id: str
    task_id: str
    project_url: str


def _base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise MiroFishConnectionError("MiroFish URL must start with http:// or https://")
    return base


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
) -> MiroFishProject:
    """Upload a seed, generate its ontology and start the graph build."""
    api = _base_url(api_url)
    frontend = _base_url(frontend_url)
    if not simulation_requirement.strip():
        raise MiroFishConnectionError("Enter a simulation question before sending the project.")

    try:
        health = session.get(f"{api}/health", timeout=5)
        health.raise_for_status()
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
        )
        ontology = _payload(ontology_response, "generate the project ontology")
        project_id = str(ontology.get("project_id", "")).strip()
        if not project_id:
            raise MiroFishConnectionError("MiroFish did not return a project ID.")

        build_response = session.post(
            f"{api}/api/graph/build",
            json={"project_id": project_id, "graph_name": project_name},
            timeout=(10, 30),
        )
        build = _payload(build_response, "start the graph build")
        return MiroFishProject(
            project_id=project_id,
            task_id=str(build.get("task_id", "")).strip(),
            project_url=f"{frontend}/process/{quote(project_id, safe='')}",
        )
    except requests.RequestException as exc:
        raise MiroFishConnectionError(
            "MiroFish is unreachable. Confirm Docker Desktop is running and use the local "
            "Streamlit app when the API address is localhost."
        ) from exc
