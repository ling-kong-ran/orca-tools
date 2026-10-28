import copy,json,pathlib,tempfile,unittest
from workflow_library import WorkflowLibrary,editor_to_prompt,exposed_parameters,ConversionError
from bridge import Bridge,apply_parameters

SCHEMAS={
 'Source':{'input':{'required':{'text':['STRING',{}],'seed':['INT',{'control_after_generate':True}],'device':[['cpu','cuda']]}},'output_node':False},
 'Save':{'input':{'required':{'value':['VALUE'],'filename_prefix':['STRING']}},'output_node':True},
 'LoadImage':{'input':{'required':{'image':[['existing.png'],{'image_upload':True}]}},'output_node':False}
}
def workflow():
 return {'nodes':[
  {'id':1,'type':'Source','widgets_values':['hello',42,'randomize','cuda']},
  {'id':2,'type':'Save','inputs':[{'name':'value','type':'VALUE','link':1}],'widgets_values':['fixed/output']},
  {'id':99,'type':'UninstalledButDisconnected','widgets_values':[]}
 ],'links':[[1,1,0,2,0,'VALUE']]}
class Adapter:
 def request(self,*args,**kwargs):return SCHEMAS
 def submit(self,prompt,client_id):self.prompt=prompt;return 'test-prompt-id'
class Tests(unittest.TestCase):
 def test_hunyuan_image_upload_and_seed_controls_map_to_api_inputs(self):
  schemas={**SCHEMAS,
   'Hy3D21LoadImageWithTransparency':{'input':{'required':{'image':[['existing.png'],{'image_upload':True}]}},'output_node':False},
   'Hy3D21MeshGenerator':{'input':{'required':{'image':['IMAGE'],'seed':['INT',{'min':0}], 'attention_mode':[['sdpa','sageattn']]}},'output_node':False}}
  graph={'nodes':[{'id':1,'type':'Hy3D21LoadImageWithTransparency','widgets_values':['existing.png','image']},
   {'id':2,'type':'Hy3D21MeshGenerator','inputs':[{'name':'image','link':1}],'widgets_values':[42,'randomize','sdpa']},
   {'id':3,'type':'Save','inputs':[{'name':'value','link':2}],'widgets_values':['render']}],
   'links':[[1,1,0,2,0,'IMAGE'],[2,2,0,3,0,'VALUE']]}
  prompt,seeds=editor_to_prompt(graph,schemas)
  self.assertEqual(prompt['1']['inputs'],{'image':'existing.png'})
  self.assertEqual(prompt['2']['inputs'],{'image':['1',0],'seed':42,'attention_mode':'sdpa'})
  self.assertEqual(seeds,[('2','seed')]);self.assertTrue(exposed_parameters(prompt,schemas)['image_1']['asset'])
  graph['nodes'][0]['widgets_values'].append('unexpected')
  with self.assertRaises(ConversionError):editor_to_prompt(graph,schemas)
 def test_tts_language_speaker_and_instruction_exposed_without_model_or_device(self):
  fields={'text':['STRING',{}],'language':[['Auto','Chinese','English','Japanese']],
          'speaker':[['Serena','Ryan']],'instruct':['STRING',{}],
          'custom_model_path':['STRING',{}],'device':[['cuda','cpu']]}
  schemas={'FB_Qwen3TTSCustomVoice':{'input':{'required':fields}}}
  prompt={'1':{'class_type':'FB_Qwen3TTSCustomVoice','inputs':{'text':'Hello','language':'Chinese','speaker':'Serena',
          'instruct':'Natural narration','custom_model_path':'C:/private/model','device':'cuda'}}}
  params=exposed_parameters(prompt,schemas)
  self.assertEqual(set(params),{'text_1','language_1','speaker_1','instruct_1'})
  self.assertEqual(params['language_1']['enum'],['Auto','Chinese','English','Japanese'])
  self.assertEqual(params['speaker_1']['enum'],['Serena','Ryan'])
  changed=apply_parameters({'prompt':prompt,'parameters':params},{'language_1':'English','speaker_1':'Ryan','instruct_1':'Speak clearly.'})
  self.assertEqual(changed['1']['inputs']['language'],'English')
  self.assertEqual(changed['1']['inputs']['device'],'cuda')
  with self.assertRaisesRegex(ValueError,'Invalid option'):apply_parameters({'prompt':prompt,'parameters':params},{'language_1':'unsupported'})
 def test_widget_order_controls_and_private_inputs(self):
  prompt,seeds=editor_to_prompt(workflow(),SCHEMAS)
  self.assertEqual(prompt['1']['inputs'],{'text':'hello','seed':42,'device':'cuda'})
  self.assertEqual(seeds,[('1','seed')]);self.assertNotIn('99',prompt)
  params=exposed_parameters(prompt,SCHEMAS)
  self.assertEqual(set(params),{'text_1','seed_1'})
  value={'prompt':prompt,'parameters':params,'random_seeds':seeds}
  self.assertEqual(apply_parameters(value,{'seed_1':123})['1']['inputs']['seed'],123)
  self.assertEqual(prompt['1']['inputs']['seed'],42)
 def test_nested_boundary_literals_and_namespacing(self):
  source=workflow()['nodes'][0];source['widgets_values_named']={'text':'inner','seed':0,'device':'cpu'}
  source['inputs']=[{'name':'text','link':10}]
  sub={'id':'group','inputNode':{'id':-10},'outputNode':{'id':-20},'nodes':[source],
       'links':[{'id':10,'origin_id':-10,'origin_slot':0,'target_id':1,'target_slot':0},
                {'id':11,'origin_id':1,'origin_slot':0,'target_id':-20,'target_slot':0}]}
  graph={'definitions':{'subgraphs':[sub]},'nodes':[
    {'id':7,'type':'group','widgets_values_named':{'caption':'outer'},'inputs':[{'name':'caption','link':None}]},
    {'id':8,'type':'Save','inputs':[{'name':'value','link':1}],'widgets_values':['fixed/output']}],
    'links':[[1,7,0,8,0,'VALUE']]}
  prompt,_=editor_to_prompt(graph,SCHEMAS)
  self.assertEqual(prompt['7:1']['inputs']['text'],'outer')
  self.assertEqual(prompt['8']['inputs']['value'],['7:1',0])
 def test_bypass_and_reroute(self):
  graph=workflow();graph['nodes'].insert(1,{'id':3,'type':'Reroute','inputs':[{'name':'value','type':'VALUE','link':1}],'outputs':[{'type':'VALUE'}]})
  graph['links']=[[1,1,0,3,0,'VALUE'],[2,3,0,2,0,'VALUE']];graph['nodes'][2]['inputs'][0]['link']=2
  prompt,_=editor_to_prompt(graph,SCHEMAS);self.assertEqual(prompt['2']['inputs']['value'],['1',0])
  graph['nodes'][1].update(type='UninstalledBypass',mode=4)
  prompt,_=editor_to_prompt(graph,SCHEMAS);self.assertEqual(prompt['2']['inputs']['value'],['1',0])
 def test_subgraph_hidden_widgets_and_optional_unconnected_socket(self):
  schemas={**SCHEMAS,'Source':{'input':{'required':{'text':['STRING',{}],'seed':['INT',{}]},'optional':{'image':['IMAGE']}},'output_node':False}}
  sub={'id':'group','inputs':[{'name':'text','type':'STRING'},{'name':'seed','type':'INT'},{'name':'image','type':'IMAGE'}],
       'inputNode':{'id':-10},'outputNode':{'id':-20},
       'nodes':[{'id':1,'type':'Source','widgets_values_named':{'text':'inner','seed':0},
                 'inputs':[{'name':'text','link':10},{'name':'seed','link':11},{'name':'image','link':12}]}],
       'links':[[10,-10,0,1,0],[11,-10,1,1,1],[12,-10,2,1,2],[13,1,0,-20,0]]}
  parent={'id':7,'type':'group','inputs':[{'name':'text','link':None},{'name':'image','link':None}],
          'widgets_values_named':{'text':'outer','seed':987}}
  graph={'definitions':{'subgraphs':[sub]},'nodes':[parent,{'id':8,'type':'Save','inputs':[{'name':'value','link':1}],'widgets_values':['out']}],
         'links':[[1,7,0,8,0]]}
  prompt,_=editor_to_prompt(graph,schemas)
  self.assertEqual(prompt['7:1']['inputs'],{'text':'outer','seed':987})
  parent.pop('widgets_values_named');parent['widgets_values']=['positional',456]
  prompt,_=editor_to_prompt(graph,schemas)
  self.assertEqual(prompt['7:1']['inputs'],{'text':'positional','seed':456})
  # A missing required value cannot become null or silently inherit an inner default.
  parent['widgets_values_named']={'text':'only'}
  with self.assertRaisesRegex(ConversionError,'required subgraph'):editor_to_prompt(graph,schemas)
 def test_subgraph_reordered_connected_input_resolves_by_name(self):
  sub={'id':'group','inputs':[{'name':'caption','type':'STRING'},{'name':'seed','type':'INT'}],
       'inputNode':{'id':-10},'outputNode':{'id':-20},
       'nodes':[{'id':1,'type':'Source','widgets_values_named':{'text':'inner','seed':0,'device':'cuda'},'inputs':[{'name':'text','link':10},{'name':'seed','link':11}]}],
       'links':[[10,-10,0,1,0],[11,-10,1,1,1],[12,1,0,-20,0]]}
  graph={'definitions':{'subgraphs':[sub]},'nodes':[
   {'id':5,'type':'PrimitiveNode','widgets_values':[123]},
   {'id':7,'type':'group','widgets_values_named':{'caption':'outer'},'inputs':[{'name':'seed','link':2},{'name':'caption','link':None}]},
   {'id':8,'type':'Save','inputs':[{'name':'value','link':1}],'widgets_values':['out']}],
   'links':[[1,7,0,8,0],[2,5,0,7,0]]}
  prompt,_=editor_to_prompt(graph,SCHEMAS)
  self.assertEqual(prompt['7:1']['inputs']['text'],'outer');self.assertEqual(prompt['7:1']['inputs']['seed'],123)
 def test_primitive_prompt_can_be_edited_without_exposing_model_fields(self):
  prompt={'1':{'class_type':'PrimitiveStringMultiline','inputs':{'value':'hello'}},
          '2':{'class_type':'UNETLoader','inputs':{'unet_name':'private.safetensors'}}}
  params=exposed_parameters(prompt,{})
  self.assertEqual(set(params),{'value_1'});self.assertEqual(params['value_1']['maxLength'],32000)
 def test_float_widget_saved_as_integer_still_accepts_fractional_override(self):
  prompt={'1':{'class_type':'Resolution','inputs':{'megapixels':1}}}
  schemas={'Resolution':{'input':{'required':{'megapixels':['FLOAT',{'min':0.1,'max':16}]}}}}
  params=exposed_parameters(prompt,schemas)
  self.assertEqual(params['megapixels_1']['type'],'number')
  changed=apply_parameters({'prompt':prompt,'parameters':params},{'megapixels_1':0.1})
  self.assertEqual(changed['1']['inputs']['megapixels'],0.1)
 def test_unknown_active_and_custom_widgets_fail(self):
  graph=workflow();graph['nodes'][0]['type']='Missing'
  with self.assertRaises(ConversionError):editor_to_prompt(graph,SCHEMAS)
  graph=workflow();graph['nodes'][0]['widgets_values'].append('unknown-extra-widget')
  with self.assertRaises(ConversionError):editor_to_prompt(graph,SCHEMAS)
 def test_directory_rescans_original_without_exposing_path(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);folder=root/'saved';folder.mkdir();adapter=Adapter();lib=WorkflowLibrary([folder],adapter)
   self.assertEqual(lib.workflows(),[])
   file=folder/'existing.json';file.write_text(json.dumps(workflow()))
   first=lib.workflows()[0];self.assertTrue(first['available'])
   graph=workflow();graph['nodes'][0]['widgets_values'][0]='new text';file.write_text(json.dumps(graph))
   updated=lib.workflows()[0];self.assertEqual(first['id'],updated['id']);self.assertEqual(updated['prompt']['1']['inputs']['text'],'new text')
   (folder/'broken.json').write_text('{')
   config={'data_dir':str(root/'bridge'),'workflow_dirs':[str(folder)]}
   bridge=Bridge(config,adapter);catalog=bridge.catalog()
   self.assertEqual(len(catalog),2);self.assertEqual(sum(w['available'] for w in catalog),1)
   encoded=json.dumps(catalog);self.assertNotIn(str(folder),encoded);self.assertNotIn('cuda',encoded);self.assertNotIn('new text',encoded)
   file.unlink();self.assertEqual(len(lib.workflows()),1)
 def test_required_asset_and_path_protection(self):
  graph={'nodes':[{'id':1,'type':'LoadImage','widgets_values':['missing.png','image']},
          {'id':2,'type':'Save','inputs':[{'name':'value','link':1}],'widgets_values':['fixed/output']}],
         'links':[[1,1,0,2,0,'VALUE']]}
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);folder=root/'saved';folder.mkdir();(folder/'image.json').write_text(json.dumps(graph))
   adapter=Adapter();bridge=Bridge({'data_dir':str(root/'bridge'),'workflow_dirs':[str(folder)]},adapter)
   item=bridge.catalog()[0];self.assertEqual(item['required_parameters'],['image_1'])
   with self.assertRaisesRegex(ValueError,'Provide these input'):bridge.submit({'workflow_id':item['id'],'request_id':'a'*32})
   for asset in ('C:/private.png','../private.png','https://example.invalid/p.png'):
    with self.assertRaisesRegex(ValueError,'relative'):bridge.submit({'workflow_id':item['id'],'request_id':'a'*32,'parameters':{'image_1':asset}})
   bridge.submit({'workflow_id':item['id'],'request_id':'a'*32,'parameters':{'image_1':'local-gpu-bridge/input.png'}})
   self.assertEqual(adapter.prompt['1']['inputs']['image'],'local-gpu-bridge/input.png')
 def test_source_directory_escape_excluded(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);folder=root/'saved';folder.mkdir();outside=root/'private.json';outside.write_text(json.dumps(workflow()))
   try:(folder/'link.json').symlink_to(outside)
   except OSError:self.skipTest('Symlink privilege unavailable')
   self.assertEqual(WorkflowLibrary([folder],Adapter()).workflows(),[])

if __name__=='__main__':unittest.main(verbosity=2)
