import keyring
import pytest
from keyring.backend import KeyringBackend

from fatball.camera.fake import FakeCamera
from fatball.demo import make_xm_clip

FPS = 12


class MemoryKeyring(KeyringBackend):
    """A throwaway keyring so no test can ever read or write the real macOS Keychain."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self.items.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring() -> MemoryKeyring:
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    return backend


@pytest.fixture
def fake_camera():
    with FakeCamera() as cam:
        yield cam


@pytest.fixture(scope="session")
def xm_clip_bytes() -> bytes:
    """A 2 s synthetic HEVC clip wrapped in Xiongmai 00 00 01 FC/FD frames."""
    return make_xm_clip(2, FPS)
