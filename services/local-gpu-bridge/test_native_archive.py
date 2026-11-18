import hashlib
import io
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import time
import unittest
import zipfile

from native_archive import extract_archive
from native_control import NativeControl


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def tar(self, entries, mode='w', name='input.tar'):
        with tarfile.open(self.root/name, mode) as archive:
            for path, kind, data in entries:
                member = tarfile.TarInfo(path)
                member.type = kind
                member.mtime = 1
                member.size = len(data) if kind == tarfile.REGTYPE else 0
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    member.linkname = '../outside'
                archive.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        return name

    def extract(self, source='input.tar', **kwargs):
        return extract_archive(self.root, source, 'output', **kwargs)

    def test_zstd_hash_contents_and_fresh_timestamp(self):
        name = self.tar([('art-src', tarfile.DIRTYPE, b''), ('art-src/mesh.glb', tarfile.REGTYPE, b'mesh')], 'w:zst', 'input.tar.zst')
        checksum = hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        result = self.extract(name, strip_components=1, expected_sha256=checksum)
        self.assertEqual((self.root/'output/mesh.glb').read_bytes(), b'mesh')
        self.assertEqual(result, {'destination':'output','files':1,'entries':2,'bytes':4})
        self.assertGreater((self.root/'output/mesh.glb').stat().st_mtime, time.time()-30)
        self.assertTrue((self.root/name).is_file())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.extract(name)

    def test_traversal_protected_names_links_collisions(self):
        for path in ('../escape', '/escape', 'C:/escape', 'art/../escape', 'art/a:stream', 'art/NUL.txt', 'art/.git/config', 'art/evil.exe', 'art/a\\b'):
            with self.subTest(path=path):
                self.tar([(path, tarfile.REGTYPE, b'x')])
                with self.assertRaises(ValueError):
                    self.extract(strip_components=1)
                self.assertFalse((self.root/'output').exists())
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            self.tar([('bad', kind, b'')])
            with self.assertRaises(ValueError):
                self.extract()
        for names in (('A/x', 'a/y'), ('a', 'a/b'), ('a', 'a')):
            self.tar([(name, tarfile.REGTYPE, b'x') for name in names])
            with self.assertRaises(ValueError):
                self.extract()
        self.assertFalse(list(self.root.glob('.archive-*')))

    def test_hash_and_limits_leave_no_output(self):
        self.tar([('a', tarfile.REGTYPE, b'123'), ('b', tarfile.REGTYPE, b'456')])
        for kwargs in ({'expected_sha256':'0'*64}, {'max_bytes':4}, {'max_files':1}):
            with self.assertRaises(ValueError):
                self.extract(**kwargs)
            self.assertFalse((self.root/'output').exists())
            self.assertFalse(list(self.root.glob('.archive-*')))

    def test_zip_and_symlink(self):
        with zipfile.ZipFile(self.root/'input.zip', 'w') as z:
            z.writestr('folder/', b'')
            z.writestr('folder/file.txt', b'text')
        self.assertEqual(self.extract('input.zip')['files'], 1)
        with zipfile.ZipFile(self.root/'link.zip', 'w') as z:
            member = zipfile.ZipInfo('link')
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(member, '../outside')
        with self.assertRaises(ValueError):
            extract_archive(self.root, 'link.zip', 'other')

    def test_async_job_idempotency_and_private_result(self):
        self.tar([('asset.txt', tarfile.REGTYPE, b'data')])
        control = NativeControl({'data_dir':str(self.root/'bridge'), 'native':{'projects':[{'id':'p','enabled':True,'root':str(self.root)}]}})
        args = dict(project_id='p', archive_path='input.tar', destination='output', request_id='a'*32)
        job = control.extract_project_archive(**args)
        deadline = time.monotonic()+5
        while control.job_status(job['id'])['status'] in ('queued','running') and time.monotonic()<deadline:
            time.sleep(.01)
        done = control.job_status(job['id'])
        self.assertEqual(done['status'], 'succeeded')
        self.assertEqual(control.extract_project_archive(**args)['id'], job['id'])
        self.assertNotIn(str(self.root), str(done))
        with self.assertRaises(ValueError):
            control.extract_project_archive(**{**args,'destination':'different'})


if __name__ == '__main__':
    unittest.main()
