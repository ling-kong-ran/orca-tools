"""Run local Git with the verified VPS time policy (UTC), without changing Windows.

Usage: python scripts/git-vps-time.py -C <repository> <git arguments...>
Existing commits and asset contents are intentionally not rewritten.
"""
import os
import re
import subprocess
import sys
from datetime import datetime,timezone


def utc_date(value):
    raw=re.fullmatch(r'@?(\d+)(?: [+-]\d{4})?',value)
    if raw:return datetime.fromtimestamp(int(raw[1]),timezone.utc).isoformat()
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('Explicit Git dates must include a timezone offset.')
    return parsed.astimezone(timezone.utc).isoformat()


def main(args=None):
    args=list(sys.argv[1:] if args is None else args)
    env=dict(os.environ)
    env['TZ']='UTC0'
    try:
        for key in ('GIT_AUTHOR_DATE','GIT_COMMITTER_DATE'):
            if env.get(key):env[key]=utc_date(env[key])
        if 'commit' in args:
            index=args.index('commit')
            # An amend normally inherits the original author's offset. Keep the
            # same instant while normalizing its representation before writing.
            revision='HEAD' if '--amend' in args[index+1:] else None
            for flag in ('-C','-c','--reuse-message','--reedit-message'):
                if flag in args[index+1:]:revision=args[args.index(flag,index+1)+1]
            if revision and '--reset-author' not in args[index+1:]:
                if not env.get('GIT_AUTHOR_DATE'):
                    date=subprocess.check_output(['git',*args[:index],'show','-s','--format=%aI',revision],env=env,text=True).strip()
                    env['GIT_AUTHOR_DATE']=utc_date(date)
                if not any(a=='--date' or a.startswith('--date=') for a in args[index+1:]):args.append('--date='+env['GIT_AUTHOR_DATE'])
            for position in range(index+1,len(args)):
                if args[position].startswith('--date='):args[position]='--date='+utc_date(args[position][7:])
                elif args[position]=='--date':args[position+1]=utc_date(args[position+1])
    except (ValueError,IndexError):
        print('Use an ISO-8601 Git date with an explicit offset; it will be converted to UTC.',file=sys.stderr)
        return 2
    return subprocess.run(['git','-c','log.date=iso-strict-local',*args],env=env).returncode


if __name__=='__main__':sys.exit(main())
