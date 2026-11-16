"""Staff identity for API tests: real signed tokens, exactly as the demo sign-in issues them.

conftest sets GOVFLOW_AUTH_SECRET to TEST_AUTH_SECRET for every test, so apps created in tests verify these.
"""

from datetime import datetime, timezone
from typing import Optional

from app.auth import issue_token

TEST_AUTH_SECRET = "test-auth-secret"


def staff(role: str, user: str, at: Optional[datetime] = None) -> dict[str, str]:
    """Headers for a signed-in user. `at`: the app's clock when a test fixes it (tokens expire against it)."""
    token, _ = issue_token(role, user, TEST_AUTH_SECRET, at or datetime.now(timezone.utc))
    return {"Authorization": f"Bearer {token}"}
