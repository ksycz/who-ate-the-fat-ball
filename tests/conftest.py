import pytest

from fatball.camera.fake import FakeCamera
from fatball.demo import make_xm_clip

FPS = 12


@pytest.fixture
def fake_camera():
    with FakeCamera() as cam:
        yield cam


@pytest.fixture(scope="session")
def xm_clip_bytes() -> bytes:
    """A 2 s synthetic HEVC clip wrapped in Xiongmai 00 00 01 FC/FD frames."""
    return make_xm_clip(2, FPS)
