"""Read locally configured workflow folders. Never expose their paths or graphs."""
import copy, hashlib, json, logging, pathlib, re, threading, time

class ConversionError(ValueError):
    pass

def links_for(graph):
    result = {}
    for link in graph.get('links', []):
        if isinstance(link, list):
            ident, origin, slot, target, target_slot = link[:5]
        else:
            ident, origin, slot, target, target_slot = (link[k] for k in ('id','origin_id','origin_slot','target_id','target_slot'))
        result[str(ident)] = (str(origin), slot, str(target), target_slot)
    return result

def input_schema(schema):
    value = schema.get('input', {})
    return {**value.get('required', {}), **value.get('optional', {})}

def widget_kind(spec):
    kind = spec[0]; options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    return (isinstance(kind, list) or kind in ('STRING','INT','FLOAT','BOOLEAN','COMBO','COMFY_DYNAMICCOMBO_V3')) and not options.get('forceInput')


def seed_control(kind, name, options):
    # These Hunyuan nodes use the frontend's seed control without declaring
    # control_after_generate in their Python input schema.
    return options.get('control_after_generate') or name == 'seed' and kind in (
        'Hy3D21MeshGenerator', 'Hy3DMultiViewsGenerator')

def widget_values(node, schema):
    named = node.get('widgets_values_named')
    if isinstance(named, dict): return copy.deepcopy(named)
    values = node.get('widgets_values') or []
    if isinstance(values, dict): return copy.deepcopy(values)
    fields = input_schema(schema)
    order = schema.get('input_order', {})
    names = [n for group in ('required','optional') for n in order.get(group, schema.get('input',{}).get(group,{}))]
    result = {}; index = 0
    for name in names:
        spec = fields[name]
        if not widget_kind(spec): continue
        if index >= len(values):
            # A converted input may no longer have a persistent widget.
            slot = next((s for s in node.get('inputs',[]) if s.get('name') == name), {})
            if slot.get('link') is not None: continue
            raise ConversionError('A saved widget value is missing. Save this workflow again in ComfyUI.')
        result[name] = copy.deepcopy(values[index]); index += 1
        options = spec[1] if len(spec)>1 and isinstance(spec[1],dict) else {}
        if seed_control(node['type'], name, options) and index < len(values) and values[index] in ('fixed','randomize','increment','decrement'):
            result['control_after_generate'] = values[index]; index += 1
        if spec[0] == 'COMFY_DYNAMICCOMBO_V3':
            selected = next((v for v in options.get('options',[]) if v.get('key') == result[name]), None)
            if not selected: raise ConversionError('A dynamic widget option is unavailable.')
            for child in input_schema({'input':selected.get('inputs',{})}):
                if index >= len(values): raise ConversionError('A dynamic widget value is missing.')
                result[name+'.'+child] = values[index]; index += 1
    # Image upload buttons are frontend widgets, not executable inputs. Custom
    # image loaders declare the same image_upload metadata as LoadImage.
    image_upload = any(len(spec)>1 and isinstance(spec[1],dict) and spec[1].get('image_upload') is True for spec in fields.values())
    if index < len(values) and (image_upload or node['type'] in ('LoadImage','LoadImageMask')) and values[index:] == ['image']: index = len(values)
    if index != len(values): raise ConversionError('This custom widget layout needs an API-format export or a dedicated adapter.')
    return result

def editor_to_prompt(workflow, schemas):
    """Resolve saved widgets, links, bypasses and nested subgraph boundaries."""
    definitions = {g['id']:g for g in workflow.get('definitions',{}).get('subgraphs',[])}
    output = {}; random_seeds = set()
    unconnected = object()
    def clone(value): return unconnected if value is unconnected else copy.deepcopy(value)
    def boundary_values(node, definition):
        # New frontend versions omit widget-only sockets from the parent node's
        # inputs array. Boundary indices belong to definition.inputs, not to that
        # shorter array. Named saved widgets also include those hidden sockets.
        for key in ('widgets_values_named', 'widgets_values'):
            if isinstance(node.get(key), dict): return copy.deepcopy(node[key])
        values = node.get('widgets_values') or []
        names = [field['name'] for field in definition.get('inputs', [])
                 if field.get('type') in ('STRING','INT','FLOAT','BOOLEAN','COMBO')]
        if len(values) != len(names):
            raise ConversionError('This subgraph widget layout needs named saved values or an API-format export.')
        return dict(zip(names, copy.deepcopy(values)))
    def expand(graph, prefix='', boundary=None, stack=()):
        nodes = {str(n['id']):n for n in graph.get('nodes',[])}
        links = links_for(graph); nested = {}; resolving = set(); built = set()
        input_id = str(graph.get('inputNode',{}).get('id',-10))
        def read_input(node, slot):
            if not 0 <= slot < len(node.get('inputs', [])): raise ConversionError('A workflow input slot is missing.')
            field = node.get('inputs',[])[slot]
            if field.get('link') is not None:
                link = links.get(str(field['link']))
                if not link: raise ConversionError('A workflow link is missing.')
                return resolve(link[0],link[1])
            values = widget_values(node, schemas.get(node['type'],{}))
            name = field.get('widget',{}).get('name',field['name'])
            if name not in values: raise ConversionError('A subgraph input value is missing.')
            return copy.deepcopy(values[name])
        def read_boundary(node, definition, slot):
            fields = definition.get('inputs')
            # Compatibility with old saved subgraphs without input definitions.
            if fields is None: return read_input(node, slot)
            if not 0 <= slot < len(fields): raise ConversionError('A subgraph boundary input is missing.')
            name = fields[slot]['name']
            matches = [i for i,field in enumerate(node.get('inputs', [])) if field.get('name') == name]
            if len(matches) > 1: raise ConversionError('A subgraph boundary name is ambiguous.')
            if matches and node['inputs'][matches[0]].get('link') is not None:
                return read_input(node, matches[0])
            values = boundary_values(node, definition)
            return copy.deepcopy(values[name]) if name in values else unconnected
        def resolve(node_id, slot):
            key = (node_id,slot)
            if key in resolving: raise ConversionError('A workflow link contains a cycle.')
            resolving.add(key)
            try:
                if node_id == input_id and boundary is not None:
                    return clone(boundary(slot))
                node = nodes.get(node_id)
                if not node: raise ConversionError('A linked node is missing.')
                kind = node['type']; mode = node.get('mode',0)
                if mode == 2: raise ConversionError('An active output depends on a muted node.')
                if kind in ('Reroute','Reroute (rgthree)'):
                    return read_input(node,0)
                if kind == 'PrimitiveNode':
                    values=node.get('widgets_values') or []
                    if not values: raise ConversionError('A primitive widget has no saved value.')
                    return copy.deepcopy(values[0])
                if mode == 4:
                    out_type = node.get('outputs',[])[slot].get('type')
                    slots = [i for i,s in enumerate(node.get('inputs',[])) if s.get('link') is not None and s.get('type') in (out_type,'*')]
                    chosen = slot if slot in slots else slots[0] if len(slots)==1 else None
                    if chosen is None: raise ConversionError('A bypass connection is ambiguous.')
                    return read_input(node,chosen)
                if kind in definitions:
                    if node_id not in nested:
                        if kind in stack or len(stack)>12: raise ConversionError('Recursive subgraphs are unsupported.')
                        nested[node_id] = expand(definitions[kind],prefix+node_id+':',lambda i:read_boundary(node,definitions[kind],i),stack+(kind,))
                    return nested[node_id](slot)
                build(node_id)
                return [prefix+node_id,slot]
            finally: resolving.remove(key)
        def build(node_id):
            if node_id in built: return
            built.add(node_id)
            node = nodes[node_id]; kind = node['type']; schema = schemas.get(kind)
            if not schema: raise ConversionError('A required node is not installed in the local ComfyUI.')
            fields = input_schema(schema); values = widget_values(node,schema); inputs = {}
            for name,value in values.items():
                root = name.split('.')[0]
                if root in fields: inputs[name] = value
            # Autogrow/dynamic inputs use dotted names, matching frontend API serialization.
            for i,field in enumerate(node.get('inputs',[])):
                if field.get('link') is not None:
                    value = read_input(node,i)
                    if value is unconnected:
                        # Optional disconnected boundary inputs are absent from
                        # API prompts, not null. Required ones must fail clearly.
                        if field['name'] in schema.get('input',{}).get('required',{}):
                            raise ConversionError('A required subgraph input is not connected.')
                        inputs.pop(field['name'], None)
                    else: inputs[field['name']] = value
            for name,spec in fields.items():
                options = spec[1] if len(spec)>1 and isinstance(spec[1],dict) else {}
                if seed_control(kind, name, options):
                    control = values.get('control_after_generate',values.get('fixed'))
                    if control == 'randomize' and name in inputs and not isinstance(inputs[name],list): random_seeds.add((prefix+node_id,name))
            output[prefix+node_id] = {'class_type':kind,'inputs':inputs}
        # Start at executable outputs, avoiding disconnected/unused branches.
        for node_id,node in nodes.items():
            if node.get('mode',0) in (2,4): continue
            if node['type'] in definitions:
                # Inner output nodes without a parent connection still need execution.
                if not any(s.get('links') for s in node.get('outputs',[])):
                    expand(definitions[node['type']],prefix+node_id+':',lambda i:read_boundary(node,definitions[node['type']],i),stack+(node['type'],))
            elif schemas.get(node['type'],{}).get('output_node'): build(node_id)
        def resolve_output(slot):
            output_id = str(graph.get('outputNode',{}).get('id',-20))
            link = next((l for l in links.values() if l[2] == output_id and l[3] == slot),None)
            if not link: raise ConversionError('A subgraph output link is missing.')
            return resolve(link[0],link[1])
        return resolve_output
    expand(workflow)
    if not output: raise ConversionError('The saved workflow has no executable output.')
    return output, sorted(random_seeds)

TEXT_FIELDS = {'text','prompt','positive','negative','negative_prompt','caption','lyrics','description','instruction','instructions'}
ASSET_FIELDS = {'image','audio','video','input_image','image_path','audio_path','video_path'}
PRIVATE_FIELDS = re.compile(r'device|gpu|vram|memory|offload|cache|filename|folder|directory|output|path|model|checkpoint|ckpt|unet|clip_name|vae_name',re.I)

def exposed_parameters(prompt, schemas):
    result = {}
    for node_id,node in prompt.items():
        fields = input_schema(schemas.get(node['class_type'],{}))
        for name,value in node['inputs'].items():
            if type(value) not in (str,int,float,bool): continue
            tts = node['class_type'].startswith('FB_Qwen3TTS')
            tts_text = tts and name in ('instruct','target_text')
            tts_choice = tts and name in ('language','speaker')
            primitive_text = node['class_type'] in ('PrimitiveString','PrimitiveStringMultiline') and name == 'value'
            definition = fields.get(name,[]); options = definition[1] if len(definition)>1 and isinstance(definition[1],dict) else {}
            asset = name in ASSET_FIELDS and (node['class_type'].startswith(('Load','VHS_Load')) or options.get('image_upload') is True)
            if not asset and PRIVATE_FIELDS.search(name): continue
            if isinstance(value,str) and name not in TEXT_FIELDS and name not in ('sampler_name','scheduler') and not asset and not tts_text and not tts_choice and not primitive_text: continue
            spec = {'node':node_id,'input':name,'type':{str:'string',int:'integer',float:'number',bool:'boolean'}[type(value)]}
            # JSON serializes whole-valued FLOAT widgets as integers (e.g. 1 MP).
            # Their public schema must still accept fractional values.
            if definition and definition[0] == 'FLOAT' and type(value) in (int,float): spec['type'] = 'number'
            if isinstance(value,str): spec['maxLength'] = 32000 if name in TEXT_FIELDS or tts_text or primitive_text else 300
            if asset: spec['asset'] = True
            if type(value) in (int,float):
                for source,target in (('min','minimum'),('max','maximum')):
                    if source in options: spec[target] = options[source]
                if 'seed' in name: spec.update(minimum=0,maximum=min(spec.get('maximum',2**53-1),2**53-1))
                if name=='batch_size':spec['maximum']=min(spec.get('maximum',8),8)
                if name=='steps':spec['maximum']=min(spec.get('maximum',150),150)
            if (name in ('sampler_name','scheduler') or tts_choice) and definition:
                choices=definition[0] if isinstance(definition[0],list) else options.get('options')
                if choices: spec['enum'] = choices
            alias = re.sub('[^a-z0-9_-]','_',name.lower()+'_'+node_id.lower())[:64]
            result[alias] = spec
    return result

def check_local_options(item, schemas):
    required = []
    by_target = {(s['node'],s['input']):name for name,s in item['parameters'].items()}
    for node_id,node in item['prompt'].items():
        if node['class_type'] not in schemas: raise ConversionError('A required node is not installed in the local ComfyUI.')
        fields = input_schema(schemas[node['class_type']])
        for name,value in node['inputs'].items():
            definition = fields.get(name,[])
            if not definition or not isinstance(definition[0],list) or isinstance(value,list): continue
            if value in definition[0]: continue
            alias = by_target.get((node_id,name))
            if alias and item['parameters'][alias].get('asset'): required.append(alias)
            else: raise ConversionError('A saved model or widget option is unavailable in the local ComfyUI.')
    item['required_parameters'] = required

class WorkflowLibrary:
    def __init__(self, folders, adapter):
        self.folders = [pathlib.Path(f).resolve() for f in folders]
        self.adapter = adapter; self.lock = threading.RLock(); self.schemas = {}; self.schema_at = 0; self.cache = {}
    def refresh_schemas(self):
        if time.monotonic()-self.schema_at < 60 and self.schemas: return
        self.schemas = self.adapter.request('/object_info',timeout=40); self.schema_at = time.monotonic(); self.cache.clear()
    def workflows(self):
        if not self.folders: return []
        with self.lock:
            schema_error = False
            try:self.refresh_schemas()
            except ValueError:schema_error = True
            result=[]
            for root_index,root in enumerate(self.folders):
                if not root.is_dir(): continue
                for file in sorted(root.rglob('*.json'))[:1000]:
                    if not file.is_file() or not file.resolve().is_relative_to(root): continue
                    relative = file.relative_to(root).as_posix()
                    ident='local-'+hashlib.sha256((str(root_index)+'/'+relative).encode()).hexdigest()[:16]
                    item={'id':ident,'name':file.stem,'description':'Saved local ComfyUI workflow.','source':'local','available':False,'parameters':{}}
                    try:
                        if schema_error: raise ConversionError('Start ComfyUI to use saved workflows.')
                        stat=file.stat()
                        if stat.st_size > 16*1024**2: raise ConversionError('The saved workflow exceeds the supported size.')
                        key=(str(file),stat.st_mtime_ns,stat.st_size)
                        if key in self.cache:
                            result.append(copy.deepcopy(self.cache[key]));continue
                        data=json.loads(file.read_text(encoding='utf-8-sig'))
                        if 'nodes' in data: prompt,seeds=editor_to_prompt(data,self.schemas)
                        else:
                            prompt=copy.deepcopy(data.get('prompt',data)); seeds=[]
                            if not prompt or not all(isinstance(n,dict) and 'class_type' in n and isinstance(n.get('inputs'),dict) for n in prompt.values()): raise ConversionError('This file is not a supported workflow.')
                        item.update(prompt=prompt,parameters=exposed_parameters(prompt,self.schemas),random_seeds=seeds,available=True)
                        check_local_options(item,self.schemas)
                        self.cache={k:v for k,v in self.cache.items() if k[0]!=str(file)}
                        self.cache[key]=copy.deepcopy(item)
                    except ConversionError as e:item.update(available=False,unavailable_reason=str(e));item.pop('prompt',None)
                    except (ValueError,KeyError,TypeError,IndexError,OSError):
                        logging.exception('Saved workflow conversion failed: %s', file)
                        item.update(available=False,unavailable_reason='This saved workflow could not be read or converted. Check the local workflow page.')
                        item.pop('prompt',None)
                    result.append(item)
            return result
