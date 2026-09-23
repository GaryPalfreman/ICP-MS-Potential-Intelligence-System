from __future__ import annotations

import pytest
import requests

from icpms_intel.mirofish import MiroFishConnectionError, create_and_build_project


class Response:
    def __init__(self, payload=None, ok=True, status_code=200):
        self._payload = payload or {}
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError()


class Session:
    def __init__(self):
        self.posts = []

    def get(self, url, timeout):
        assert url == "http://localhost:5001/health"
        return Response({"status": "ok"})

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if url.endswith("/ontology/generate"):
            return Response({"success": True, "data": {"project_id": "proj_123"}})
        return Response({"success": True, "data": {"task_id": "task_456"}})


def test_create_and_build_project_uses_official_api_sequence():
    session = Session()
    project = create_and_build_project(
        "# Seed", "What changes next?", session=session
    )

    assert project.project_id == "proj_123"
    assert project.task_id == "task_456"
    assert project.project_url == "http://localhost:3000/process/proj_123"
    assert session.posts[0][0].endswith("/api/graph/ontology/generate")
    assert session.posts[0][1]["data"]["simulation_requirement"] == "What changes next?"
    assert session.posts[1][0].endswith("/api/graph/build")
    assert session.posts[1][1]["json"] == {
        "project_id": "proj_123",
        "graph_name": "ICP-MS Potential Intelligence",
    }


def test_create_and_build_project_reports_api_failure():
    session = Session()
    session.post = lambda *args, **kwargs: Response(
        {"success": False, "error": "bad model"}, ok=False, status_code=502
    )

    with pytest.raises(MiroFishConnectionError, match="bad model"):
        create_and_build_project("# Seed", "Question", session=session)


def test_create_and_build_project_rejects_invalid_url():
    with pytest.raises(MiroFishConnectionError, match="must start"):
        create_and_build_project("# Seed", "Question", api_url="localhost:5001")
