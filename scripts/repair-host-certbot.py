#!/usr/bin/env python3
"""Repair existing LensRhyme host HTTP-01 routing and standalone renewal conflict."""
import datetime
from pathlib import Path
import shutil
import subprocess

config=Path('/etc/nginx/sites-enabled/lensrhyme.conf').resolve()
text=config.read_text()
old='    return 301 https://$host$request_uri;'
new='    location / {\n        return 301 https://$host$request_uri;\n    }'
# A return at server scope runs before the challenge location and redirects it.
if old in text:
    backup=config.with_name(config.name+'.before-certbot-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
    shutil.copy2(config,backup)
    config.write_text(text.replace(old,new,1))
    try:
        subprocess.run(['nginx','-t'],check=True)
    except subprocess.CalledProcessError:
        shutil.copy2(backup,config)
        raise
    subprocess.run(['systemctl','reload','nginx'],check=True)
renewal=Path('/etc/letsencrypt/renewal/lens-rhyme.tensorbytes.com.conf')
text=renewal.read_text()
if 'authenticator = standalone' in text:
    shutil.copy2(renewal,renewal.with_suffix('.conf.before-webroot'))
    text=text.replace('authenticator = standalone','authenticator = webroot\nwebroot_path = /var/www/letsencrypt,')
    renewal.write_text(text)
hook=Path('/etc/letsencrypt/renewal-hooks/deploy/20-nginx-reload')
hook.parent.mkdir(parents=True,exist_ok=True)
if not hook.exists():
    hook.write_text('#!/bin/sh\nset -eu\n/usr/sbin/nginx -t\n/bin/systemctl reload nginx\n')
    hook.chmod(0o755)
print('HTTP-01 route, webroot renewal, and nginx deploy reload configured.')
