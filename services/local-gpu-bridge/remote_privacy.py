"""Filter host/account metadata at the authenticated remote JSON boundary.

Project text, language choices and geometry fields remain usable. This is not a
sandbox for arbitrary programs or a rewrite of user-authored media content.
"""
import datetime
import ipaddress
import json
import os
import re
import socket

PRIVATE = {
    'hostname', 'computername', 'machinename', 'username', 'publicip', 'privateip',
    'ip', 'ipv4', 'ipv6', 'macaddress', 'networkinterfaces', 'hardwareinfo',
    'deviceid', 'accountfingerprint', 'sessionfingerprint', 'accountemail',
    'email', 'phone', 'phonenumber', 'accountregion', 'clientregion',
    'country', 'countrycode', 'geolocation', 'systemlocale', 'browserlocale',
    'acceptlanguage', 'accesskeyid', 'secretaccesskey', 'sessiontoken',
    'accesstoken', 'refreshtoken', 'authorization', 'cookie', 'cookies',
    'geoip', 'territory', 'browserlanguages', 'systemlanguage', 'oslocale',
    'timezoneoffset', 'utcoffset', 'localtime', 'localtimestamp',
    'ownername', 'owneravatar', 'useravatar', 'phoneprefix', 'dialcode',
    'currency', 'currencycode',
    'credential', 'credentialstore', 'hostname', 'localaddress', 'account',
    'accountid', 'userid', 'host', 'endpoint', 'serverregion', 'regionname',
}
ZONE_KEYS = {'timezone', 'timezoneid', 'localtimezone', 'systemtimezone', 'timezonename'}
LOCAL_ZONE = re.compile(r'(?i)Asia/(?:Shanghai|Chongqing|Chungking|Harbin|Hong_Kong|Macao|Macau)|China Standard Time|中国标准时间|北京时间')
PROVIDER = re.compile(r'(?i)\b(?:[a-z0-9-]+\.)*(?:bcebos\.com|tripo3d\.(?:com|ai))\b')
ISO = re.compile(r'(?<!\w)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)(?!\w)')


def utc_time(match):
    try:
        return datetime.datetime.fromisoformat(match[0].replace('Z', '+00:00')).astimezone(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
    except ValueError: return '[invalid timestamp]'


def remote_text(text, resources=False):
    text = ISO.sub(utc_time, text)
    text = LOCAL_ZONE.sub('[local timezone]', text)
    # Local paths never become URLs or download handles. Known Tripo paths are
    # converted to scoped handles before this final boundary filter runs.
    text = re.sub(r'(?i)\b[A-Z]:[\\/][^\r\n"\']*', '[local path]', text)
    text = re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', '[address]', text)
    def ipv6(match):
        try: ipaddress.IPv6Address(match[0].split('%')[0]); return '[address]'
        except ValueError: return match[0]
    text = re.sub(r'(?<!\w)(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.%]*(?!\w)', ipv6, text)
    for identity in {socket.gethostname(), os.environ.get('COMPUTERNAME', ''), os.environ.get('USERNAME', '')}:
        if len(identity) >= 3: text = re.sub(r'(?i)(?<!\w)' + re.escape(identity) + r'(?!\w)', '[local identity]', text)
    # CDN links carry account/region hints and signatures. The scoped file
    # download API is the remote consumer's supported path for these resources.
    if resources: text = re.sub(r'https?://[^\s"<>\\]+', '[remote resource]', text)
    text = PROVIDER.sub('[service]', text)
    return text


def remote_json(value, resources=False):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = re.sub(r'[^a-z0-9]', '', key.lower())
            if normalized in PRIVATE: continue
            if normalized in ZONE_KEYS: continue
            if normalized in ('region', 'locale') and isinstance(item, str): continue
            if resources and isinstance(item, str) and item.startswith(('http://', 'https://')) and key != '$schema': continue
            if resources and normalized in ('error', 'message', 'detail') and isinstance(item, str):
                item = re.sub(r'(?i)\b(?:China|Chinese)[ -]site\b|\bregion[\s:=]+(?:cn|china)\b|中国站|国内站', 'configured service', item)
            result[key] = remote_json(item, resources)
        return result
    if isinstance(value, list): return [remote_json(item, resources) for item in value]
    if isinstance(value, str):
        if value.startswith(('data:image/', 'data:audio/', 'data:application/')): return value
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)): return json.dumps(remote_json(parsed, resources), ensure_ascii=False)
        except (ValueError, TypeError): pass
        return remote_text(value, resources)
    return value
