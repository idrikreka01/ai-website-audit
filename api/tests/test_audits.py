"""
Tests for audit endpoints.

These tests cover the critical behaviors specified in the acceptance criteria:
- POST creates queued session
- GET returns 404 for missing session
- GET artifacts returns empty list for new session
- POST enqueues RQ job
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from fastapi import status


def test_create_audit_session(client):
    """Test that POST /audits creates a session with status='queued'."""
    response = client.post(
        "/audits",
        json={
            "url": "https://example.com",
            "mode": "standard",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "id" in data
    assert data["status"] == "queued"
    assert data["url"] == "https://example.com/"

    # Verify the session exists in the database
    session_id = data["id"]
    get_response = client.get(f"/audits/{session_id}")
    assert get_response.status_code == status.HTTP_200_OK
    session_data = get_response.json()
    assert session_data["status"] == "queued"
    assert session_data["mode"] == "standard"
    assert session_data["attempts"] == 0
    assert session_data["low_confidence"] is False
    assert "crawl_policy_version" in session_data
    assert "config_snapshot" in session_data


def test_get_audit_session_not_found(client):
    """Test that GET /audits/{id} returns 404 for a non-existent session."""
    non_existent_id = str(uuid4())
    response = client.get(f"/audits/{non_existent_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert "not found" in data["detail"].lower()


def test_get_audit_artifacts_empty_list(client):
    """Test that GET /audits/{id}/artifacts returns empty list for a new session."""
    # Create a session
    create_response = client.post(
        "/audits",
        json={
            "url": "https://example.com",
            "mode": "standard",
        },
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    session_id = create_response.json()["id"]

    # Get artifacts (should be empty list)
    artifacts_response = client.get(f"/audits/{session_id}/artifacts")
    assert artifacts_response.status_code == status.HTTP_200_OK
    artifacts = artifacts_response.json()
    assert isinstance(artifacts, list)
    assert len(artifacts) == 0


def test_get_audit_artifacts_not_found(client):
    """Test that GET /audits/{id}/artifacts returns 404 for a non-existent session."""
    non_existent_id = str(uuid4())
    response = client.get(f"/audits/{non_existent_id}/artifacts")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert "not found" in data["detail"].lower()


def test_url_normalization(client):
    """Test that URLs are normalized correctly."""
    # Test that scheme-less URLs are rejected (HttpUrl requires scheme)
    response = client.post(
        "/audits",
        json={
            "url": "example.com",
            "mode": "standard",
        },
    )
    # Pydantic HttpUrl validation should reject scheme-less URLs
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Test with valid URL that has trailing slash (should be normalized)
    response2 = client.post(
        "/audits",
        json={
            "url": "https://example.com/",
            "mode": "standard",
        },
    )
    assert response2.status_code == status.HTTP_201_CREATED
    # The normalized URL should remove trailing slash (except for root path)
    data = response2.json()
    assert data["url"] == "https://example.com/"

    # Test with valid URL without trailing slash
    response3 = client.post(
        "/audits",
        json={
            "url": "https://example.com/path",
            "mode": "standard",
        },
    )
    assert response3.status_code == status.HTTP_201_CREATED
    data3 = response3.json()
    assert data3["url"] == "https://example.com/path"


def test_invalid_url_rejected(client):
    """Test that invalid URLs are rejected with 400."""
    response = client.post(
        "/audits",
        json={
            "url": "not-a-valid-url",
            "mode": "standard",
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@patch("api.services.audit_service.enqueue_audit_job")
def test_create_audit_enqueues_job(mock_enqueue, client):
    """Test that POST /audits enqueues an RQ job after creating the session."""
    # Mock the enqueue function to return successfully (no exception)
    mock_enqueue.return_value = None

    response = client.post(
        "/audits",
        json={
            "url": "https://example.com",
            "mode": "standard",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    session_id = data["id"]

    # Verify enqueue was called with correct arguments
    mock_enqueue.assert_called_once()
    call_args = mock_enqueue.call_args
    # First positional arg is the UUID object, second is the normalized URL
    assert str(call_args[0][0]) == session_id  # session_id (UUID)
    assert call_args[0][1] == "https://example.com/"  # normalized URL
