import hashlib
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.build_release import build


class ReleaseTests(unittest.TestCase):
    def test_source_release_excludes_settings_memory_and_environments(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            files={'main.py':'print("app")','requirements.txt':'requests',
                   'core/face_model.obj':'model asset','config/api_keys.json.example':'{}',
                   'config/api_keys.json':'fake-key-must-not-ship','config/private.key':'fake-private-key',
                   'memory/long_term.json':'private memory','memory/state.db':'database',
                   '.venv/package.py':'not part of source','screenshots/private.png':'private screenshot',
                   'dashboard/templates/index.html':'page'}
            for name,content in files.items():
                path=root/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(content)
            output=root/'dist/release.zip'
            count,digest=build(output,root)
            self.assertEqual(count,5)
            with ZipFile(output) as archive:
                names=archive.namelist()
                self.assertIn('Ultron/core/face_model.obj',names)
                self.assertIn('Ultron/config/api_keys.json.example',names)
                self.assertNotIn('Ultron/config/api_keys.json',names)
                self.assertNotIn('Ultron/memory/long_term.json',names)
            self.assertEqual(digest,hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertIn(digest,output.with_suffix('.zip.sha256').read_text())
