import pathlib,sys,tempfile,types,unittest,unittest.mock
import native_blender_vrm as vrm


class BlenderVrmTests(unittest.TestCase):
    def setUp(self):
        self.bpy=unittest.mock.MagicMock();self.addons=unittest.mock.MagicMock()
        self.bpy.context.preferences.addons.__contains__.return_value=True
        self.modules=unittest.mock.patch.dict(sys.modules,{'bpy':self.bpy,'addon_utils':self.addons})
        self.modules.start();self.addCleanup(self.modules.stop)

    def test_missing_extensions_do_not_claim_operator_support(self):
        with unittest.mock.patch.object(vrm.importlib.util,'find_spec',return_value=None):
            self.assertEqual(vrm.capabilities(),{'vrm_import':False,'vrm_export':False})
        self.bpy.ops.import_scene.vrm.get_rna_type.assert_not_called()

    def test_factory_startup_registers_extension_and_preferences(self):
        self.addons.check.side_effect=[(False,False),(True,True)]
        with unittest.mock.patch.object(vrm.importlib.util,'find_spec',return_value=object()):
            self.assertTrue(vrm.ensure_vrm())
        self.addons.enable.assert_called_once_with('bl_ext.user_default.vrm',default_set=True,persistent=True)

    def test_running_extension_without_preferences_is_repaired_without_reregister(self):
        self.addons.check.return_value=(False,True)
        self.bpy.context.preferences.addons.__contains__.return_value=False
        with unittest.mock.patch.object(vrm.importlib.util,'find_spec',return_value=object()):
            self.assertTrue(vrm.ensure_vrm())
        self.addons.enable.assert_not_called()
        self.assertEqual(self.bpy.context.preferences.addons.new.return_value.module,'bl_ext.user_default.vrm')

    def test_cancelled_import_is_not_reported_as_success(self):
        self.bpy.ops.import_scene.vrm.return_value={'CANCELLED'}
        with unittest.mock.patch.object(vrm,'ensure_vrm',return_value=True),self.assertRaisesRegex(ValueError,'did not finish'):
            vrm.operate(pathlib.Path('avatar.vrm'))


if __name__=='__main__':unittest.main()
