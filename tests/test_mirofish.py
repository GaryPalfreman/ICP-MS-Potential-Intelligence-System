from __future__ import annotations

import pytest
import requests

from icpms_intel.mirofish import (
    MiroFishConnectionError,
    configured_value,
    create_and_build_project,
    default_connection_mode,
)


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

    def get(self, url, timeout, headers=None):
        assert url.endswith("/health")
        self.health_headers = headers or {}
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
    assert session.health_headers == {}


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


def test_hosted_connection_requires_public_https_endpoints():
    with pytest.raises(MiroFishConnectionError, match="publicly reachable HTTPS"):
        create_and_build_project(
            "# Seed", "Question", api_url="http://mirofish.example.com", mode="hosted"
        )
    with pytest.raises(MiroFishConnectionError, match="cannot reach localhost"):
        create_and_build_project(
            "# Seed", "Question", api_url="https://localhost:5001", mode="hosted"
        )
    with pytest.raises(MiroFishConnectionError, match="public HTTPS MiroFish interface"):
        create_and_build_project(
            "# Seed",
            "Question",
            api_url="https://mirofish.example.com",
            frontend_url="http://localhost:3000",
            mode="hosted",
        )


def test_hosted_connection_passes_optional_gateway_token():
    session = Session()
    create_and_build_project(
        "# Seed",
        "Question",
        api_url="https://mirofish.example.com",
        frontend_url="https://mirofish.example.com",
        mode="hosted",
        api_token="secret-token",
        session=session,
    )

    assert session.health_headers == {"Authorization": "Bearer secret-token"}
    assert session.posts[0][1]["headers"] == {
        "Authorization": "Bearer secret-token"
    }
    assert session.posts[1][1]["headers"] == {
        "Authorization": "Bearer secret-token"
    }


def test_cloudflare_access_service_token_is_sent_from_server_only():
    session = Session()
    create_and_build_project(
        "# Seed",
        "Question",
        api_url="https://mirofish.example.com",
        frontend_url="https://mirofish.example.com",
        mode="hosted",
        access_client_id="client-id",
        access_client_secret="client-secret",
        session=session,
    )

    expected = {
        "CF-Access-Client-Id": "client-id",
        "CF-Access-Client-Secret": "client-secret",
    }
    assert session.health_headers == expected
    assert session.posts[0][1]["headers"] == expected
    assert session.posts[1][1]["headers"] == expected


def test_cloudflare_access_requires_both_service_token_values():
    with pytest.raises(MiroFishConnectionError, match="Configure both"):
        create_and_build_project(
            "# Seed",
            "Question",
            api_url="https://mirofish.example.com",
            frontend_url="https://mirofish.example.com",
            mode="hosted",
            access_client_id="client-id",
        )


def test_unreachable_host_error_is_actionable_without_echoing_credentials():
    class UnreachableSession(Session):
        def get(self, url, timeout, headers=None):
            raise requests.ConnectionError("connection refused")

    with pytest.raises(MiroFishConnectionError) as error:
        create_and_build_project(
            "# Seed",
            "Question",
            api_url="https://mirofish.example.com",
            frontend_url="https://mirofish.example.com",
            mode="hosted",
            api_token="secret-token",
            session=UnreachableSession(),
        )

    assert "host 'mirofish.example.com'" in str(error.value)
    assert "public HTTPS endpoint is online" in str(error.value)
    assert "secret-token" not in str(error.value)


def test_health_success_followed_by_api_network_failure_names_failed_stage():
    class UnreachableUploadSession(Session):
        def post(self, url, **kwargs):
            raise requests.ConnectionError("connection reset")

    with pytest.raises(MiroFishConnectionError, match="ontology request") as error:
        create_and_build_project(
            "# Seed",
            "Question",
            api_url="http://localhost:5001",
            session=UnreachableUploadSession(),
        )

    assert "health check" not in str(error.value)


def test_hosted_health_error_reports_http_status_not_network_failure():
    class UnauthorizedSession(Session):
        def get(self, url, timeout, headers=None):
            return Response(ok=False, status_code=401)

    with pytest.raises(MiroFishConnectionError, match="HTTP 401"):
        create_and_build_project(
            "# Seed",
            "Question",
            api_url="https://mirofish.example.com",
            frontend_url="https://mirofish.example.com",
            mode="hosted",
            session=UnauthorizedSession(),
        )


def test_connection_mode_uses_config_then_app_url():
    assert default_connection_mode(
        "https://icp-ms-potential-intelligence-system.streamlit.app",
    ) == "hosted"
    assert default_connection_mode("http://localhost:8501") == "local"
    assert default_connection_mode(
        "http://localhost:8501", configured_mode="hosted"
    ) == "hosted"
    assert default_connection_mode(
        "https://icp-ms-potential-intelligence-system.streamlit.app",
        configured_mode="local",
    ) == "hosted"
    assert default_connection_mode(
        "http://localhost:8501", api_url="https://mirofish.example.com"
    ) == "hosted"


def test_environment_setting_takes_precedence_over_streamlit_secret(monkeypatch):
    monkeypatch.setenv("MIROFISH_API_URL", "https://from-env.example.com")
    assert configured_value(
        "MIROFISH_API_URL",
        {"MIROFISH_API_URL": "https://from-secrets.example.com"},
    ) == "https://from-env.example.com"
    monkeypatch.delenv("MIROFISH_API_URL")
    assert configured_value(
        "MIROFISH_API_URL",
        {"MIROFISH_API_URL": "https://from-secrets.example.com"},
    ) == "https://from-secrets.example.com"
