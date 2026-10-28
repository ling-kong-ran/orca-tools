"""Local credential import; never called by a remote MCP tool."""
import datetime,json,pathlib,re,subprocess,time,urllib.request,urllib.error
from native_tripo import find_browser,NO_WINDOW

def verify_cookie(cookie,opener=None):
    if not isinstance(cookie,str) or not re.fullmatch(r'[A-Za-z0-9_+=/-]{32,16000}',cookie):
        raise ValueError('Expected only the session Cookie value, without a header name or line breaks.')
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request('https://auth-cn.tripo3d.com/sessions/whoami?tokenize_as=default_jwt',
        headers={'Cookie':'ory_kratos_session='+cookie,'Accept':'application/json','User-Agent':'Orca-Tools-Tripo-Login'})
    try:
        with opener.open(req,timeout=30) as response:d=json.load(response)
    except urllib.error.HTTPError as e:
        raise ValueError('China-site session validation returned HTTP '+str(e.code)+'. The Cookie may have expired.') from None
    if not d.get('active') or not d.get('tokenized'):
        raise ValueError('The China-site session is not active or did not yield a Studio token.')
    return {'authenticated':True,'expires_at':d.get('expires_at')}

def import_cookie(control,cookie):
    if control.region!='cn':raise ValueError('Cookie import currently supports only region cn.')
    verified=verify_cookie(cookie)
    control.begin_login();process=None
    try:
        control.runtime_root()
        control.shutdown_backend()
        browser=find_browser(control.browser)
        # Only our dedicated, marked profile is touched. No default browser profile is read.
        process=subprocess.Popen([browser,'--headless=new','--user-data-dir='+str(control.profile_dir()),
            '--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(control.site['cdp']),
            '--no-first-run','--no-default-browser-check','about:blank'],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=NO_WINDOW)
        helper=pathlib.Path(__file__).with_name('tripo-cookie-import.mjs')
        payload={'cdp_port':control.site['cdp'],'cookie':cookie,'expires_at':verified['expires_at']}
        child=subprocess.run(['node',str(helper)],input=json.dumps(payload),text=True,encoding='utf-8',
            capture_output=True,timeout=60,creationflags=NO_WINDOW)
        if child.returncode:raise ValueError('The session could not be stored in the dedicated browser profile.')
        process.wait(timeout=20)
        return {**verified,'stored_in':'dedicated_browser_profile','cookie_logged':False,'region':'cn'}
    finally:
        if process is not None and process.poll() is None:process.terminate()
        control.end_login()
