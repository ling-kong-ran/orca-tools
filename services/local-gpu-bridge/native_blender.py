"""Restricted Blender command worker. Loaded only in the managed Blender instance."""
import bpy,json,pathlib,sys,math,os
from mathutils import Vector
settings=json.loads(pathlib.Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf-8'))
root=pathlib.Path(settings['project']).resolve();spool=pathlib.Path(settings['spool']);out=pathlib.Path(settings['outputs']).resolve()
spool.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)

def local_file(value,suffixes):
    if not isinstance(value,str) or '\\' in value or ':' in value or value.startswith('/') or any(p in ('..','.','') for p in value.split('/')):raise ValueError('Invalid project-relative file')
    p=(root/value).resolve()
    if not p.is_relative_to(root) or p.suffix.lower() not in suffixes:raise ValueError('File is outside the approved project')
    return p
def vec(value):
    if not isinstance(value,list) or len(value)!=3 or not all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=1e6 for x in value):raise ValueError('Invalid vector')
    return value
def object_info(obj):return {'name':obj.name,'type':obj.type,'location':list(obj.location),'rotation':list(obj.rotation_euler),'scale':list(obj.scale)}
def execute(command,args,job_id):
    if command in ('execute_code','run_script'):
        code=args.get('code') if command=='execute_code' else local_file(args['path'],{'.py'}).read_text(encoding='utf-8-sig')
        namespace={'__name__':'__main__','__file__':str(root/args['path']) if command=='run_script' else '<remote-blender>', 'bpy':bpy,'project_root':root,'parameters':args.get('parameters',{})}
        previous=list(sys.argv);cwd=os.getcwd()
        try:
            os.chdir(root);sys.argv=[namespace['__file__'],*args.get('user_args',[])]
            exec(compile(code,namespace['__file__'],'exec'),namespace,namespace)
            value=json.loads(json.dumps(namespace.get('result'),default=str))
            return {'executed':True,'result':value}
        finally:sys.argv=previous;os.chdir(cwd)
    if command=='scene_info':return {'objects':[object_info(o) for o in list(bpy.context.scene.objects)[:500]],'object_count':len(bpy.context.scene.objects)}
    if command=='open':
        file=local_file(args['path'],{'.blend'})
        bpy.ops.wm.open_mainfile(filepath=str(file),load_ui=False,use_scripts=False)
        return {'opened':args['path']}
    if command=='save':
        file=local_file(args['path'],{'.blend'});file.parent.mkdir(parents=True,exist_ok=True)
        if file.exists() and not args.get('replace',False):raise ValueError('File exists; explicit replace is required')
        bpy.ops.wm.save_as_mainfile(filepath=str(file),check_existing=False)
        return {'saved':args['path']}
    if command=='create_primitive':
        kinds={'cube':bpy.ops.mesh.primitive_cube_add,'sphere':bpy.ops.mesh.primitive_uv_sphere_add,'plane':bpy.ops.mesh.primitive_plane_add,'cylinder':bpy.ops.mesh.primitive_cylinder_add,'cone':bpy.ops.mesh.primitive_cone_add,'torus':bpy.ops.mesh.primitive_torus_add,'monkey':bpy.ops.mesh.primitive_monkey_add}
        if args.get('kind') not in kinds:raise ValueError('Unsupported primitive')
        kinds[args['kind']]();obj=bpy.context.object;obj.name=args.get('name','Object')[:120]
        for name in ('location','scale','rotation'):
            if name in args:setattr(obj,'rotation_euler' if name=='rotation' else name,vec(args[name]))
        return object_info(obj)
    if command in ('set_transform','set_material','delete_object'):
        obj=bpy.data.objects.get(args['name'])
        if obj is None:raise ValueError('Object not found')
        if command=='delete_object':bpy.data.objects.remove(obj,do_unlink=True);return {'deleted':True}
        if command=='set_transform':
            for name in ('location','scale','rotation'):
                if name in args:setattr(obj,'rotation_euler' if name=='rotation' else name,vec(args[name]))
            return object_info(obj)
        color=args['color']
        if not isinstance(color,list) or len(color)!=4 or any(type(x) not in (int,float) or not 0<=x<=1 for x in color):raise ValueError('Invalid material color')
        mat=bpy.data.materials.new(name='LocalMaterial');mat.diffuse_color=color;mat.use_nodes=True
        bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=color
        for key,title in [('roughness','Roughness'),('metallic','Metallic')]:
            if key in args:
                value=args[key]
                if type(value) not in (int,float) or not 0<=value<=1:raise ValueError('Invalid material value')
                bsdf.inputs[title].default_value=value
        if not hasattr(obj.data,'materials'):raise ValueError('Object cannot use materials')
        obj.data.materials.clear();obj.data.materials.append(mat);return {'material_applied':True}
    if command=='set_camera':
        camera=bpy.context.scene.camera
        if not camera:
            data=bpy.data.cameras.new('LocalCamera');camera=bpy.data.objects.new('LocalCamera',data);bpy.context.collection.objects.link(camera);bpy.context.scene.camera=camera
        camera.location=vec(args['location']);target=Vector(vec(args.get('target',[0,0,0])))
        camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.lens=float(args.get('lens',50));return {'camera_updated':True}
    if command=='render':
        scene=bpy.context.scene;engine=args.get('engine','cycles')
        if engine=='cycles' and 'cycles' not in bpy.context.preferences.addons:bpy.ops.preferences.addon_enable(module='cycles')
        scene.render.engine='CYCLES' if engine=='cycles' else 'BLENDER_EEVEE'
        if engine=='cycles':
            preferences=bpy.context.preferences.addons['cycles'].preferences;preferences.compute_device_type='OPTIX';preferences.get_devices()
            devices=[d for d in preferences.devices if d.type=='OPTIX']
            if not devices:raise ValueError('Hardware rendering is unavailable')
            for device in preferences.devices:device.use=device.type=='OPTIX'
            scene.cycles.device='GPU';scene.cycles.samples=int(args.get('samples',32))
        scene.render.resolution_x=int(args.get('width',1280));scene.render.resolution_y=int(args.get('height',720));scene.render.resolution_percentage=100
        # Compositor outputs may target arbitrary files in an opened .blend. Disable them.
        scene.render.use_compositing=False;scene.render.image_settings.file_format='PNG';scene.render.filepath=str(out/(job_id+'.png'))
        bpy.ops.render.render(write_still=True);return {'artifact':job_id+'.png','hardware_render':True}
    if command=='import_asset':
        file=local_file(args['path'],{'.glb','.gltf','.obj','.ply','.stl'})
        if file.suffix.lower() in ('.glb','.gltf'):bpy.ops.import_scene.gltf(filepath=str(file))
        elif file.suffix.lower()=='.obj':bpy.ops.wm.obj_import(filepath=str(file))
        elif file.suffix.lower()=='.ply':bpy.ops.wm.ply_import(filepath=str(file))
        else:bpy.ops.wm.stl_import(filepath=str(file))
        return {'imported':args['path']}
    if command=='export_asset':
        file=local_file(args['path'],{'.glb','.obj'});file.parent.mkdir(parents=True,exist_ok=True)
        if file.exists() and not args.get('replace',False):raise ValueError('File exists; explicit replace is required')
        if file.suffix.lower()=='.glb':bpy.ops.export_scene.gltf(filepath=str(file),export_format='GLB',export_yup=True)
        else:bpy.ops.wm.obj_export(filepath=str(file))
        return {'exported':args['path']}
    raise ValueError('Operation is not exposed')

def service():
    for file in sorted(spool.glob('*.request.json')):
        job_id=file.name.split('.')[0];claimed=file.with_suffix('.running');file.replace(claimed)
        try:
            request=json.loads(claimed.read_text(encoding='utf-8'))
            result={'ok':True,'result':execute(request['command'],request.get('arguments',{}),job_id)}
        except Exception:
            # Raw exceptions stay in the local app log, not in the remote response.
            import traceback;traceback.print_exc();result={'ok':False,'error':'Blender operation failed. Check the local application log.'}
        target=spool/(job_id+'.response.json');temp=target.with_suffix('.tmp');temp.write_text(json.dumps(result),encoding='utf-8');temp.replace(target)
    return 0.1

bpy.app.timers.register(service,first_interval=0.2,persistent=True)
(spool/'ready.json').write_text(json.dumps({'ready':True}),encoding='utf-8')
