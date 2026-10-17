import os
from pathlib import Path

import pytest

from livereload.handlers import MtimeStaticFileHandler


@pytest.fixture
def css_file(tmp_path: Path) -> str:
    path = tmp_path / "style.css"
    _ = path.write_text("body {}")
    return str(path)


def test_cached_version_is_content_hash(css_file: str) -> None:
    version = MtimeStaticFileHandler._get_cached_version(css_file)
    expected = MtimeStaticFileHandler.get_content_version(css_file)
    assert version == expected
    assert MtimeStaticFileHandler._static_hashes[css_file] == expected


def test_cached_version_changes_with_mtime(css_file: str) -> None:
    first = MtimeStaticFileHandler._get_cached_version(css_file)
    _ = Path(css_file).write_text("body { color: red }")
    stat = os.stat(css_file)
    os.utime(css_file, (stat.st_atime, stat.st_mtime + 10))
    second = MtimeStaticFileHandler._get_cached_version(css_file)
    assert first != second
