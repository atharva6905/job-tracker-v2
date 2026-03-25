"""Tests for the keepalive ping job."""
from unittest.mock import patch, MagicMock

from app.jobs.keepalive_job import ping_health


class TestPingHealth:
    def test_successful_ping(self):
        """ping_health calls /health endpoint and returns normally."""
        with patch("app.jobs.keepalive_job.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            ping_health()
        mock_get.assert_called_once_with("http://localhost:8000/health", timeout=5)

    def test_connection_error_logged_not_raised(self):
        """Connection failure is logged at WARNING but does not propagate."""
        import requests

        with patch("app.jobs.keepalive_job.requests.get") as mock_get:
            mock_get.side_effect = requests.ConnectionError("refused")
            # Must not raise
            ping_health()
        mock_get.assert_called_once()

    def test_timeout_logged_not_raised(self):
        """Timeout is logged at WARNING but does not propagate."""
        import requests

        with patch("app.jobs.keepalive_job.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("timed out")
            ping_health()
        mock_get.assert_called_once()
