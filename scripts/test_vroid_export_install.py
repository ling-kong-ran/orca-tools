"""Validate source patching and installation guards without starting Studio."""
import importlib.util, pathlib, tempfile, unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('export_installer', pathlib.Path(__file__).with_name('install-vroid-export.py'))
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)


class ExportInstallerTests(unittest.TestCase):
    def test_patch_registers_main_thread_operation_and_requires_current_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder); project = source/'plugin/VroidStudioMcp'
            (project/'Commands/Handlers').mkdir(parents=True); (project/'MCP').mkdir()
            (project/'Commands/CommandDispatcher.cs').write_text('"save", "categories"\n["save"] = SessionHandlers.Save,', encoding='utf-8')
            (project/'Plugin.cs').write_text('MessagesI18n.Install();', encoding='utf-8')
            (project/'MCP/McpHost.cs').write_text('T("sections",', encoding='utf-8')
            self.assertEqual(installer.patch_source(source), project)
            self.assertIn('["export_vrm"] = ExportHandlers.Export', (project/'Commands/CommandDispatcher.cs').read_text(encoding='utf-8'))
            self.assertIn('OnScreenActivate', (project/'Plugin.cs').read_text(encoding='utf-8'))
            self.assertIn('T("export_vrm"', (project/'MCP/McpHost.cs').read_text(encoding='utf-8'))
            self.assertEqual((project/'Commands/Handlers/ExportHandlers.cs').read_bytes(),
                             (installer.ROOT/'services/local-gpu-bridge/vroid-export/ExportHandlers.cs').read_bytes())
            with self.assertRaisesRegex(ValueError, 'does not match'): installer.patch_source(source)

    def test_modified_source_archive_is_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder); archive = root/'source.zip'; archive.write_bytes(b'modified')
            with patch.object(installer.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'checksum'): installer.build(root, archive, root/'out.dll')
                run.assert_not_called()

    def test_running_managed_editor_must_be_saved_and_stopped(self):
        root = pathlib.Path('managed').resolve()
        result = type('Result', (), {'stdout': str(root/'VRoidStudio-LocalGpu.exe')+'\n'})()
        with patch.object(installer.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'Save and stop'): installer.require_stopped(root)


if __name__ == '__main__': unittest.main()
