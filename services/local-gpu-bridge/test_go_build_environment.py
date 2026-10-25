import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from native_script import go_build_environment


class GoEnvironmentTests(unittest.TestCase):
    def test_explicit_caches_survive_disabled_user_config_without_enabling_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            native={'go_root':str(root/'sdk'),'go_path':str(root/'workspace'),
                    'go_module_cache':str(root/'modules'),'go_build_cache':str(root/'cache')}
            with patch.dict(os.environ,{'TEST_SECRET':'private','ORCA_TOKEN':'private','GOFLAGS':'-toolexec=bad','GOPROXY':'https://example.invalid','GOMODCACHE':'wrong'},clear=True):
                env=go_build_environment(native)
            self.assertEqual(env['GOMODCACHE'],str(root/'modules'))
            self.assertEqual(env['GOCACHE'],str(root/'cache'))
            self.assertEqual(env['GOPATH'],str(root/'workspace'))
            for key,value in {'GOENV':'off','GOPROXY':'off','GOSUMDB':'off','GOTOOLCHAIN':'local','GOWORK':'off','CGO_ENABLED':'0','GOFLAGS':''}.items():
                self.assertEqual(env[key],value)
            self.assertNotIn('TEST_SECRET',env);self.assertNotIn('ORCA_TOKEN',env)

    def test_relative_cache_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'absolute'):
            go_build_environment({'go_root':'sdk','go_module_cache':'relative'})


if __name__=='__main__':unittest.main()
