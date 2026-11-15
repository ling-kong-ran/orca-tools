import base64, json, pathlib, sys, tempfile, textwrap, unittest, unittest.mock, shutil, subprocess
import native_tripo
from native_tripo import TripoControl, REGIONS

FAKE_MCP = textwrap.dedent('''
    import json, sys
    tools = [{"name": n, "inputSchema": {"type": "object"}} for n in
             ("tripo_get_status", "tripo_start_workflow", "tripo_set_account", "tripo_clear_account", "tripo_open_gallery")]
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg: continue
        if msg["method"] == "initialize": result = {"serverInfo": {"name": "fake"}}
        elif msg["method"] == "tools/list": result = {"tools": tools}
        else: result = {"content": [{"type": "text", "text": json.dumps(msg["params"]["arguments"])}], "isError": False}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
''')

SERVER = '\n'.join(['var STUDIO_ORIGIN = "https://studio.tripo3d.ai";', 'var STUDIO_API_BASE_URL = "https://api.tripo3d.ai";',
                    'return `TripoStudioMCP:${digest3}:studio.tripo3d.ai`;', 'var TRIPO_ACCOUNT_ORIGIN = "https://www.tripo3d.ai";',
                    'var TRIPO_MCP_HTTP_PORT = 32175;', 'var ALLOWED = ["tripo3d.ai", "tripo3d.com"];',
                    '`tripo-studio-global-server\\0${options2.identity ?? currentUserIdentity()}`',
                    'session2.status().authenticated || credentialStatus?.state === "available"',
                    'if ((options2.platform ?? process.platform) !== "win32") return new InteractionRequiredCredentialStore();',
                    native_tripo.UPLOAD_CLIENT, native_tripo.ACTION_READ] + [old for old, _ in native_tripo.SCHEDULER_PATCHES])

# Pinned upstream snippets: a changed bundle must fail closed rather than receive
# a partial auth patch. Behavioral tests below exercise the replacement itself.
GLOBAL_AUTH = '''if (isRecoverableCaptureFailure(error3)) break;
} catch {
          finish(
            () => reject(
              new TripoError("AUTH_CAPTURE_FAILED", "Failed to verify the signed-in Studio account on the trusted page.", {
while (!settled && Date.now() < readinessDeadline) {
            let signedIn = false;
if (stableSignedInChecks < SIGNED_IN_STABILITY_CHECKS && !settled) {
if (!triggered && !settled) throw new Error("verification request unavailable");
while (!settled && Date.now() < readinessDeadline) {
            let result2;
      "--headless=new",
!args.includes("--headless=new") || normalizedPath('''


class TripoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.cache = self.root / 'cache'
        plugin = self.cache / '0.8.0' / 'mcp'; plugin.mkdir(parents=True)
        (plugin / 'server.mjs').write_text(SERVER, encoding='utf-8')
        (plugin / 'bootstrap.mjs').write_text('var TRIPO_MCP_HTTP_PORT = 32175;\n', encoding='utf-8')
        fake = self.root / 'fake_mcp.py'; fake.write_text(FAKE_MCP, encoding='utf-8')
        self.config = {'data_dir': str(self.root / 'bridge'), 'tripo': {'region': 'cn', 'plugin_cache': str(self.cache),
                       'data_dir': str(self.root / 'data'), 'asset_root': str(self.root / 'assets')}}
        self.control = TripoControl(self.config, command=[sys.executable, str(fake)])
        self.addCleanup(self.control.stop)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for runtime patch tests')
    def test_china_storage_endpoint_is_pinned_and_disables_aws_acceleration(self):
        code = '''const TripoError=Error;const transport={useAccelerateEndpoint:true};
function options(host){const token={host};return {''' + native_tripo.CN_UPLOAD_CLIENT + '''};}
const good=options('https://s3.bj.bcebos.com/');
if(good.endpoint!=='https://s3.bj.bcebos.com'||good.region!=='bj'||!good.forcePathStyle||good.useAccelerateEndpoint)throw Error('Invalid BOS configuration');
for(const host of ['https://example.com','s3.bj.bcebos.com.evil.test','http://s3.bj.bcebos.com','s3.bj.bcebos.com/path']){
let rejected=false;try{options(host)}catch{rejected=true}if(!rejected)throw Error('Unsafe endpoint accepted');}
'''
        subprocess.run(['node', '--input-type=module', '-e', code], check=True, capture_output=True)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for runtime patch tests')
    def test_recovered_action_reads_resume_only_existing_owned_operations(self):
        code = '''class Recovered {
#index={get:async()=>({})};count=0;status='running';owned=true;
async #backendSnapshot(){return {status:this.status}}
#ownsBindingAccount(){return this.owned}
#observe(){this.count++}
async #publicAction(binding,snapshot){return snapshot}
async get(actionId){''' + native_tripo.RECOVER_ACTION_READ + '''}}
for(const status of ['submitted','queued','running','staged','committing','failed','cancelled','succeeded']){
for(const owned of [true,false]){const r=new Recovered();r.status=status;r.owned=owned;await r.get('existing');
if(r.count!==(owned&&['submitted','queued','running'].includes(status)?1:0))throw Error('Unsafe recovery');}}
'''
        subprocess.run(['node', '--input-type=module', '-e', code], check=True, capture_output=True)

    def test_login_lock_blocks_calls_even_with_a_live_bootstrap(self):
        self.control.ensure_started()
        with unittest.mock.patch.object(self.control, 'login_active', return_value=True):
            with self.assertRaisesRegex(ValueError, 'sign-in is in progress'): self.control.ensure_started()

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for runtime patch tests')
    def test_scheduler_counters_stay_valid_after_many_acceptances_and_congestions(self):
        patches = dict(native_tripo.SCHEDULER_PATCHES)
        code = '''const current={concurrency_limit:3,consecutive_accepted:0,consecutive_congestion:0};
for(let i=0;i<5000;i++){''' + patches['current.consecutive_accepted += 1;'] + patches['current.consecutive_congestion += 1;'] + '''
if(current.consecutive_accepted>5||current.consecutive_congestion>1000)throw Error('State schema overflow');}
if(current.consecutive_accepted!==5||current.consecutive_congestion!==1000)throw Error('Incorrect saturation');
function legacy(){const document2={accounts:{a:{concurrency_limit:10,consecutive_accepted:5}}};const accountFingerprint='a';const clone8=x=>({...x});const defaultSchedulerState=()=>({});
''' + patches['return clone8(document2.accounts[accountFingerprint] ?? defaultSchedulerState());'] + '''}
if(legacy().concurrency_limit!==3)throw Error('Legacy concurrency was not clamped');
'''
        subprocess.run(['node', '--input-type=module', '-e', code], check=True, capture_output=True)

    def test_public_times_are_utc_and_upload_names_have_no_local_timestamp(self):
        raw = {'created_at': '2026-10-29T11:22:23+08:00', 'timezone': 'Asia/Shanghai',
               'nested': json.dumps({'time': '2026-10-29T12:00:00+08:00'}), 'other': 'keep'}
        public = self.control.public_times(raw)
        self.assertEqual(public['created_at'], '2026-10-29T03:22:23Z')
        self.assertEqual(public['timezone'], 'UTC')
        self.assertEqual(json.loads(public['nested'])['time'], '2026-10-29T04:00:00Z')
        uploaded = self.control.upload('image.png', base64.b64encode(b'png').decode())
        self.assertRegex(uploaded['path'], r'^tripo:inputs/[a-f0-9]{32}-image\.png$')

    def test_legacy_upload_handles_are_opaque_and_still_downloadable(self):
        folder = self.control.roots['inputs']; folder.mkdir(parents=True)
        old = '20261029-031037-concept.png'; (folder / old).write_bytes(b'png')
        returned = json.loads(self.control.to_handles(json.dumps({'path': str(folder / old), 'source_name': old})))
        self.assertNotIn('20261029-031037', json.dumps(returned))
        self.assertEqual(self.control.file(returned['path']).read_bytes(), b'png')
        self.assertEqual(self.control.to_local(returned['path']), str(folder / old))
        restored = TripoControl(self.config)
        self.assertEqual(restored.file(returned['path']).read_bytes(), b'png')
        self.assertEqual(self.control.file('tripo:inputs/' + old).read_bytes(), b'png')

    def test_status_keeps_only_auth_queue_and_credit_information(self):
        raw = {'session': {'authenticated': True, 'source': 'cookie', 'device_id_available': True},
               'gallery': {'local_address': 'http://127.0.0.1:1'}, 'credential': 'native',
               'balance': {'available': True, 'summary': {'member': {'type': 'private'},
                  'wallet': {'total_credit': 12, 'expiring_credit': 2}}},
               'scheduler': {'running': 1, 'queued': 0, 'concurrencyLimit': 3}}
        result = self.control.necessary_status({'structuredContent': raw, 'content': [{'type': 'text', 'text': json.dumps(raw)}]})
        status = result['structuredContent']
        self.assertEqual(status['session'], {'authenticated': True})
        self.assertEqual(status['balance']['credits']['total_credit'], 12)
        self.assertNotIn('gallery', status); self.assertNotIn('credential', status)
        self.assertEqual(json.loads(result['content'][0]['text']), status)

    def test_account_tools_stay_on_the_pc(self):
        listed = self.control.tools()
        names = [t['name'] for t in listed['tools']]
        self.assertEqual(names, ['tripo_get_status', 'tripo_start_workflow'])
        self.assertTrue(json.dumps(listed, ensure_ascii=False).isascii())
        self.assertNotIn('region', listed)
        for name in ('tripo_set_account', 'tripo_clear_account', 'tripo_open_gallery', 'shell', 'get_status'):
            with self.assertRaises(ValueError): self.control.call(name, {})

    def test_gallery_route_ids_resolve_to_downloadable_files(self):
        archive = self.control.roots['archive']; folder = archive / 'items/model_generation--one'
        folder.mkdir(parents=True); (folder / 'model-1.glb').write_bytes(b'glb')
        (archive / 'catalog.json').write_text(json.dumps({'items': {'model_generation--one': {
            'files': [{'file_id': 'model-1', 'relative_path': 'items/model_generation--one/model-1.glb'}]}}}))
        route = 'files/model_generation--one/model-1'
        result = json.loads(self.control.to_handles(json.dumps({'gallery_files': [route]})))
        handle = result['gallery_files'][0]
        self.assertEqual(handle, 'tripo:archive/items/model_generation--one/model-1.glb')
        self.assertEqual(self.control.file(handle).read_bytes(), b'glb')
        self.assertEqual(self.control.file('tripo:archive/' + route).read_bytes(), b'glb')
        nested = json.dumps({'text': json.dumps({'gallery_files': [route]})})
        self.assertEqual(json.loads(json.loads(self.control.to_handles(nested))['text'])['gallery_files'], [handle])
        with self.assertRaises(ValueError): self.control.file('tripo:archive/files/unknown/model-1')

    def test_paths_cross_as_handles(self):
        upload = self.control.upload('concept.png', base64.b64encode(b'png').decode())
        self.assertTrue(upload['path'].startswith('tripo:inputs/'))
        reply = self.control.call('tripo_start_workflow', {'steps': [{'source': {'image_path': upload['path']}}]})
        echoed = reply['content'][0]['text']
        self.assertIn(upload['path'], echoed); self.assertNotIn(str(self.root), echoed)
        local = self.control.to_local(upload['path'])
        self.assertEqual(pathlib.Path(local).read_bytes(), b'png')
        archive = self.root / 'data' / 'archive' / 'w1'; archive.mkdir(parents=True); (archive / 'model.glb').write_bytes(b'glb')
        text = self.control.to_handles(json.dumps({'file': str(archive / 'model.glb')}))
        self.assertEqual(json.loads(text)['file'], 'tripo:archive/w1/model.glb')
        nested = json.dumps({'text': json.dumps({'file': str(archive / 'model.glb'), 'dir': str(archive)})})
        inner = json.loads(json.loads(self.control.to_handles(nested))['text'])
        self.assertEqual(inner, {'file': 'tripo:archive/w1/model.glb', 'dir': 'tripo:archive/w1'})
        self.assertEqual(self.control.file('tripo:archive/w1/model.glb').read_bytes(), b'glb')
        for bad in ('tripo:inputs/../../secret.txt', 'tripo:archive/C:/Windows/win.ini', str(archive / 'model.glb'), 'tripo:other/x'):
            with self.assertRaises(ValueError): self.control.file(bad)
        for name in ('../x.png', 'run.exe', '.hidden.png', 'a b.png'):
            with self.assertRaises(ValueError): self.control.upload(name, base64.b64encode(b'x').decode())

    def test_china_copy_changes_only_the_site_settings(self):
        root = self.control.runtime_root()
        self.assertNotEqual(root, self.cache / '0.8.0')
        server = (root / 'mcp/server.mjs').read_text(encoding='utf-8')
        site = REGIONS['cn']
        for expected in (f'"{site["studio"]}"', f'"{site["api"]}"', f'"{site["account"]}"', ':studio.tripo3d.com`', 'PORT = 32176'):
            self.assertIn(expected, server)
        self.assertIn('["tripo3d.ai", "tripo3d.com"]', server)
        self.assertIn('orca-tripo-cn-server\\0${process.env.TRIPO_DATA_DIR}', server)
        self.assertIn('process.env.TRIPO_REUSE_BROWSER_SESSION === "1"', server)
        self.assertIn('32176', (root / 'mcp/bootstrap.mjs').read_text(encoding='utf-8'))
        self.assertIn('32175', (self.cache / '0.8.0/mcp/bootstrap.mjs').read_text(encoding='utf-8'))
        stamp = (root / '.bridge-patch.json').stat().st_mtime_ns
        self.assertEqual(self.control.runtime_root(), root)
        self.assertEqual((root / '.bridge-patch.json').stat().st_mtime_ns, stamp)
        env = self.control.environment()
        self.assertEqual(env['TRIPO_DATA_DIR'], str(self.root / 'data'))
        self.assertEqual(env['TRIPO_CHROME_CDP_URL'], 'http://127.0.0.1:9223')
        self.assertEqual(env['TRIPO_REUSE_BROWSER_SESSION'], '1')
        self.assertEqual(env['TRIPO_COOKIE_ONLY'],'1')

    def test_changed_plugin_is_refused_not_half_patched(self):
        newer = self.cache / '0.9.0' / 'mcp'; newer.mkdir(parents=True)
        (newer / 'server.mjs').write_text(SERVER.replace('var STUDIO_ORIGIN', 'const STUDIO_ORIGIN'), encoding='utf-8')
        (newer / 'bootstrap.mjs').write_text('var TRIPO_MCP_HTTP_PORT = 32175;\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'bridge update'): self.control.runtime_root()
        self.assertFalse((self.root / 'bridge/tripo/cn/0.9.0').exists())

    def test_global_region_reuses_login_without_changing_the_site(self):
        control = TripoControl({**self.config, 'tripo': {**self.config['tripo'], 'region': 'global'}})
        source = self.cache / '0.8.0/mcp/server.mjs'
        fixture = SERVER + '\n' + GLOBAL_AUTH
        source.write_text(fixture, encoding='utf-8')
        root = control.runtime_root()
        self.assertNotEqual(root, self.cache / '0.8.0')
        server = (root / 'mcp/server.mjs').read_text(encoding='utf-8')
        self.assertIn('process.env.TRIPO_REUSE_BROWSER_SESSION === "1"', server)
        for setting in ('studio', 'api', 'account'):
            self.assertIn('"' + REGIONS['global'][setting] + '"', server)
        self.assertEqual(source.read_text(encoding='utf-8'), fixture)
        self.assertEqual((root / 'mcp/bootstrap.mjs').read_bytes(), (self.cache / '0.8.0/mcp/bootstrap.mjs').read_bytes())
        self.assertEqual(control.environment()['TRIPO_BROWSER_HEADLESS'], '0')
        self.assertNotIn('TRIPO_BROWSER_HEADLESS', self.control.environment())
        with self.assertRaises(ValueError): TripoControl({'tripo': {'region': 'eu'}})

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for runtime patch tests')
    def test_global_capture_requires_official_page_and_independent_account_proof(self):
        code = '''import assert from 'node:assert/strict';
const STUDIO_ORIGIN='https://studio.tripo3d.ai';
const AUTH_VERIFICATION_URL='https://api.tripo3d.ai/v2/studio/user/profile/payment';
const MAX_AUTH_VERIFICATION_BYTES=1024;
const apiEnvelopeSchema={safeParse(value){return {success:Number.isInteger(value?.code),data:value}}};
class Capture {
#config={tokenCaptureTimeoutMs:1000,requestTimeoutMs:1000};
async run(page,context2){
let triggered=false,settled=false,captured;
const finish=fn=>{if(!settled){settled=true;fn()}};
const resolve3=value=>captured=value;
const expectedVerificationUrl=AUTH_VERIFICATION_URL+'?auth_capture_nonce=test';
''' + native_tripo.GLOBAL_CAPTURE_FALLBACK + '''
return captured;
}}
async function attempt(options={}){
 const frame={},bodies=[],calls=[];let observes=0,reloads=0;
 const request={url:()=>options.requestUrl??options.url??AUTH_VERIFICATION_URL,
  method:()=>options.method??'GET',frame:()=>options.foreignFrame?{}:frame,
  allHeaders:async()=>({authorization:options.authorization??'Bearer test-only',
   'x-tripo-device-id':'test-device','x-tripo-region':'test'})};
 const body=value=>{const b=Buffer.from(value);bodies.push(b);return b};
 const response={url:()=>options.url??AUTH_VERIFICATION_URL,request:()=>request,
  status:()=>options.status??200,body:async()=>body(options.body??'{"code":0,"data":{}}')};
 const page={mainFrame:()=>frame,url:()=>options.pageUrl??STUDIO_ORIGIN+'/workspace/generate',
  waitForResponse:async predicate=>{observes++;if(options.initialMiss&&observes===1||!predicate(response))throw Error('not matched');return response},
  reload:async()=>{reloads++;return {status:()=>options.navigationStatus??200}},title:async()=>options.title??'Tripo Studio',
  getByRole:()=>({first:()=>({isVisible:async()=>options.signedOut??false})})};
 let disposed=false;
 const context2={request:{get:async(url,opts)=>{
  calls.push(url);assert.equal(url,AUTH_VERIFICATION_URL+'?auth_capture_nonce=test');
  assert.equal(opts.maxRedirects,0);assert.equal(opts.headers.authorization,'Bearer test-only');
  assert.equal(opts.headers.origin,STUDIO_ORIGIN);
  return {status:()=>options.proofStatus??200,url:()=>options.proofUrl??url,
   body:async()=>body(options.proofBody??'{"code":0,"data":{}}'),dispose:async()=>{disposed=true}};
 }}};
 try{return {captured:await new Capture().run(page,context2),calls,disposed,reloads}}
 finally{for(const b of bodies)assert.ok(b.every(byte=>byte===0),'response body must be wiped')}
}
const good=await attempt();assert.equal(good.captured.authorization,'Bearer test-only');
assert.equal(good.calls.length,1);assert.ok(good.disposed);assert.equal(good.reloads,0);
const loaded=await attempt({initialMiss:true});assert.equal(loaded.reloads,1);
assert.equal(loaded.captured.authorization,'Bearer test-only');
for(const options of [
 {url:'https://api.tripo3d.ai.evil.test/v2/studio/user/profile/payment'},
 {url:'https://api.tripo3d.ai/v2/other'}, {url:'https://user@api.tripo3d.ai/v2/studio/user/profile/payment'},
 {requestUrl:'https://evil.test/redirect'}, {foreignFrame:true},{method:'POST'},
 {pageUrl:'https://evil.test/'},{initialMiss:true,navigationStatus:403},{title:'Just a moment'}, {signedOut:true},
 {status:401},{body:'{"code":1}'},{body:'invalid json'},{body:' '.repeat(1025)},
 {authorization:'Basic test-only'},{authorization:'Bearer '+ 'x'.repeat(16384)},
 {proofStatus:403},{proofUrl:AUTH_VERIFICATION_URL},{proofBody:'{"code":1}'},
 {proofBody:' '.repeat(1025)}
])await assert.rejects(()=>attempt(options));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for runtime patch tests')
    def test_visible_browser_mode_preserves_automation_ownership_requirement(self):
        pairs = dict(native_tripo.patches('global')['mcp/server.mjs'])
        predicate = pairs['!args.includes("--headless=new") || normalizedPath('].split(' || normalizedPath(')[0]
        code = '''import assert from 'node:assert/strict';
function rejected(args,mode){process.env.TRIPO_BROWSER_HEADLESS=mode;return ''' + predicate + '''}
assert.equal(rejected(['--enable-automation'],'0'),false);
assert.equal(rejected([],'0'),true);
assert.equal(rejected(['--enable-automation','--headless=new'],'0'),true);
assert.equal(rejected(['--headless=new'],'1'),false);
assert.equal(rejected(['--enable-automation'],'1'),true);
'''
        subprocess.run(['node', '--input-type=module', '-e', code], check=True, capture_output=True)

    def test_login_profile_is_marked_for_the_plugin(self):
        profile = self.control.profile_dir()
        marker = json.loads((profile / native_tripo.MARKER).read_text(encoding='utf-8'))
        self.assertEqual(marker['schema_version'], 1); self.assertEqual(len(marker['ownership_token']), 43)
        self.assertEqual(self.control.profile_dir(), profile)

    def test_stopped_backend_restarts_and_repeats_only_reads(self):
        gone = {'content': [{'type': 'text', 'text': 'The Bootstrap could not connect to its local backend.'}], 'isError': True}
        fine = {'content': [{'type': 'text', 'text': '{}'}], 'isError': False}
        with unittest.mock.patch.object(self.control, '_call', side_effect=[gone, fine]) as call, unittest.mock.patch.object(self.control, 'stop') as stop:
            self.assertFalse(self.control.call('tripo_get_status', {})['isError'])
            self.assertEqual(call.call_count, 2); stop.assert_called_once()
        with unittest.mock.patch.object(self.control, '_call', side_effect=[gone, fine]) as call, unittest.mock.patch.object(self.control, 'stop') as stop:
            self.assertTrue(self.control.call('tripo_start_workflow', {})['isError'])
            self.assertEqual(call.call_count, 1); stop.assert_called_once()

    def test_descriptions_reach_the_vps_in_english(self):
        tool = native_tripo.english_tool({'name': 'tripo_get_status', 'description': '\u67e5\u770b\u72b6\u6001',
                                          'inputSchema': {'type': 'object', 'properties': {'page': {'type': 'integer', 'description': '\u9875\u7801'}}}})
        self.assertTrue(tool['description'].startswith('Show the Studio'))
        self.assertNotIn('description', tool['inputSchema']['properties']['page'])
        caps = {'operations': [{'name': 'model.generate', 'description': '\u751f\u6210', 'input_schema': {'title': '\u6a21\u578b', 'type': 'object'}}]}
        result = native_tripo.english_capabilities({'structuredContent': caps, 'content': [{'type': 'text', 'text': json.dumps(caps)}]})
        self.assertTrue(json.dumps(result, ensure_ascii=False).isascii())
        self.assertEqual(result['structuredContent']['operations'][0]['description'], native_tripo.OPERATION_TEXT['model.generate'])
        for name in native_tripo.TOOL_TEXT: self.assertTrue(native_tripo.TOOL_TEXT[name].isascii())

    def test_keepalive_waits_for_a_login(self):
        listed = self.control.tools()['tools']; self.control.stop()
        self.control.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.control.login_lock().write_text(str(__import__('os').getpid()), encoding='utf-8')
        self.assertTrue(self.control.login_active())
        with self.assertRaisesRegex(ValueError, 'sign-in is in progress'): self.control.call('tripo_get_status', {})
        self.assertEqual(self.control.tools()['tools'], listed)
        self.control.login_lock().write_text('999999999', encoding='utf-8')
        self.assertFalse(self.control.login_active()); self.assertFalse(self.control.login_lock().exists())

    def test_vps_client_lists_only_tripo_tools(self):
        sys.path.insert(0, str(pathlib.Path(__file__).parent / 'plugin'))
        import client
        fake = unittest.mock.Mock()
        fake.request.return_value = {'tools': [{'name': 'tripo_get_status'}, {'name': 'run_workflow'}, {'name': 'tripo_upload'}, 'bad']}
        names = [t['name'] for t in client.Client.tripo_tools(fake)]
        self.assertEqual(names, ['tripo_upload', 'tripo_download', 'tripo_get_status'])
        fake.request.side_effect = ValueError('offline')
        self.assertEqual([t['name'] for t in client.Client.tripo_tools(fake)], ['tripo_upload', 'tripo_download'])


if __name__ == '__main__':
    unittest.main()
