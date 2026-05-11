import os
import pytest
from unittest.mock import patch, MagicMock


def test_maven_client_raises_when_env_missing():
    """_maven_client() raises RuntimeError if any of the four env vars is absent."""
    import importlib
    with patch.dict(os.environ, {}, clear=False):
        for key in ("MAVEN_ORG_ID", "MAVEN_AGENT_ID", "MAVEN_APP_ID", "MAVEN_APP_SECRET"):
            os.environ.pop(key, None)
        # Re-import to get a clean module state with env cleared
        import maven_orchestrator
        importlib.reload(maven_orchestrator)
        with pytest.raises(RuntimeError, match="Missing Maven env vars"):
            maven_orchestrator._maven_client()


def test_maven_client_returns_client_with_valid_env():
    """_maven_client() returns a MavenAGI instance when all env vars are set."""
    env = {
        "MAVEN_ORG_ID": "org1",
        "MAVEN_AGENT_ID": "agent1",
        "MAVEN_APP_ID": "app1",
        "MAVEN_APP_SECRET": "secret1",
    }
    with patch.dict(os.environ, env):
        with patch("maven_orchestrator.MavenAGI") as mock_cls:
            import maven_orchestrator
            maven_orchestrator._maven_client()
            mock_cls.assert_called_once_with(
                organization_id="org1",
                agent_id="agent1",
                app_id="app1",
                app_secret="secret1",
            )
