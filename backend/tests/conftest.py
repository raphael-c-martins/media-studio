"""Os testes usam pastas temporárias: nunca tocam no banco, nos logs ou nos downloads reais."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="media_studio_tests_"))
os.environ["MS_DATA_DIR"] = str(_TEST_ROOT / "data")
os.environ["MS_LOGS_DIR"] = str(_TEST_ROOT / "logs")
os.environ["MS_DOWNLOADS_DIR"] = str(_TEST_ROOT / "downloads")
os.environ["MS_TEMP_DIR"] = str(_TEST_ROOT / "temp")
os.environ.pop("MS_ACCESS_TOKEN", None)
os.environ.pop("MS_HOST", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

LOCAL_HEADERS = {"X-Media-Studio": "1"}


@pytest.fixture(scope="session")
def test_root() -> Path:
    return _TEST_ROOT


@pytest.fixture()
def client():
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
