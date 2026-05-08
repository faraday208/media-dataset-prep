"""Meta repo integration testleri için fixture'lar."""
import os
import time

import pytest


def _touch(path, mtime):
    with open(path, 'wb') as f:
        f.write(b'\x00')
    os.utime(path, (mtime, mtime))


@pytest.fixture
def mini_dataset(tmp_path):
    """
    Pipeline'ın 0. adımı için minimal kaynak: alt klasörlü, mtime'lı.
    5 jpg + 1 mp4 + 1 mp3, root + 2 alt klasör.
    """
    base = tmp_path / "raw"
    base.mkdir()
    base_time = time.time() - 86400

    _touch(base / "IMG_001.jpg", base_time + 10)
    _touch(base / "IMG_002.jpg", base_time + 20)
    _touch(base / "audio.mp3", base_time + 30)

    cam = base / "camera"
    cam.mkdir()
    _touch(cam / "DSC_3847.jpg", base_time + 40)
    _touch(cam / "DSC_3848.jpg", base_time + 50)

    misc = base / "misc"
    misc.mkdir()
    _touch(misc / "video.mp4", base_time + 60)
    _touch(misc / "screenshot.jpg", base_time + 70)

    return base
