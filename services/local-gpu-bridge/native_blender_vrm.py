"""Load an installed VRM extension in the factory-startup managed Blender."""
import importlib.util


def ensure_vrm():
    import bpy, addon_utils
    for module in ('bl_ext.user_default.vrm', 'bl_ext.blender_org.vrm', 'io_scene_vrm'):
        try:
            if importlib.util.find_spec(module) is None: continue
            if not addon_utils.check(module)[1]:
                addon_utils.enable(module, default_set=True, persistent=True)
            if not addon_utils.check(module)[1]: continue
            if module not in bpy.context.preferences.addons:
                preference = bpy.context.preferences.addons.new(); preference.module = module
            bpy.ops.import_scene.vrm.get_rna_type()
            bpy.ops.export_scene.vrm.get_rna_type()
            return True
        except Exception:
            import traceback; traceback.print_exc()
    return False


def capabilities():
    available = ensure_vrm()
    return {'vrm_import': available, 'vrm_export': available}


def operate(file, export=False):
    import bpy
    if not ensure_vrm(): raise ValueError('Install and enable VRM Add-on for Blender locally first.')
    operation = bpy.ops.export_scene.vrm if export else bpy.ops.import_scene.vrm
    result = operation(filepath=str(file))
    if 'FINISHED' not in result: raise ValueError('VRM operation did not finish. Check model validation and license confirmations locally.')
