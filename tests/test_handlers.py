import os
import shutil
import tempfile
import unittest

from livereload.handlers import MtimeStaticFileHandler


class TestMtimeStaticFileHandler(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'style.css')
        with open(self.path, 'w') as f:
            f.write('body {}')

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_cached_version_is_content_hash(self):
        version = MtimeStaticFileHandler._get_cached_version(self.path)
        expected = MtimeStaticFileHandler.get_content_version(self.path)
        assert version == expected
        assert MtimeStaticFileHandler._static_hashes[self.path] == expected

    def test_cached_version_changes_with_mtime(self):
        first = MtimeStaticFileHandler._get_cached_version(self.path)
        with open(self.path, 'w') as f:
            f.write('body { color: red }')
        stat = os.stat(self.path)
        os.utime(self.path, (stat.st_atime, stat.st_mtime + 10))
        second = MtimeStaticFileHandler._get_cached_version(self.path)
        assert first != second
