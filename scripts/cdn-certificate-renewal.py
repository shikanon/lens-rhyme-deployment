#!/usr/bin/env python3
"""Renew ACME certificates through bucket HTTP-01 and deploy to Alibaba/Volc CDN."""
import argparse
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
CONFIG = Path(os.environ.get('LENS_CDN_CONFIG', '/etc/lens-cdn-renewal/config.json'))
STATE = Path('/var/lib/lens-cdn-renewal/status.json')
HELPER = Path('/usr/local/libexec/lens-cdn-certificate-cloud.py')


def protected_json(path):
    path = Path(path)
    mode = path.stat()
    if mode.st_uid != 0 or stat.S_IMODE(mode.st_mode) & 0o077:
        raise RuntimeError('credential_file_must_be_root_owned_mode_600')
    return json.loads(path.read_text())


def sdk(config, target, operation, **kwargs):
    credential_path = target['credentials_file'] if operation == 'aliyun-api' else target.get('origin_credentials_file', target['credentials_file'])
    credentials = protected_json(credential_path)
    payload = {'credentials': credentials, 'target': target, 'operation': operation, **kwargs}
    result = subprocess.run(['docker','exec','-i',config['backend_container'],'python','-c',HELPER.read_text()], input=json.dumps(payload), text=True, capture_output=True, timeout=90)
    try:
        response = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError('cloud_adapter_failed') from None
    if result.returncode or response.get('error'):
        raise RuntimeError('cloud_api:' + response.get('code','failed'))
    return response


def volc(target, action, body):
    credentials = protected_json(target['credentials_file'])
    host = 'cdn.volcengineapi.com'
    query = urllib.parse.urlencode(sorted({'Action':action,'Version':'2021-03-01'}.items()))
    now = dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    date = now[:8]
    payload = json.dumps(body,separators=(',',':')).encode()
    digest = hashlib.sha256(payload).hexdigest()
    headers = {'host':host,'x-content-sha256':digest,'x-date':now}
    signed = ';'.join(sorted(headers))
    canonical = 'POST\n/\n'+query+'\n'+''.join(k+':'+headers[k]+'\n' for k in sorted(headers))+'\n'+signed+'\n'+digest
    scope = date+'/cn-north-1/CDN/request'
    string = 'HMAC-SHA256\n'+now+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
    key = credentials['sk'].encode()
    for value in [date,'cn-north-1','CDN','request']:
        key = hmac.new(key,value.encode(),hashlib.sha256).digest()
    signature = hmac.new(key,string.encode(),hashlib.sha256).hexdigest()
    headers['Authorization'] = 'HMAC-SHA256 Credential='+credentials['ak']+'/'+scope+', SignedHeaders='+signed+', Signature='+signature
    headers['content-type'] = 'application/json'
    request = urllib.request.Request('https://'+host+'/?'+query, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        result = json.loads(error.read())
    cloud_error = result.get('ResponseMetadata',{}).get('Error')
    if cloud_error:
        raise RuntimeError('cloud_api:'+cloud_error['Code'])
    return result.get('Result',{})


def lineage(target):
    return Path('/etc/letsencrypt/live') / target['domain']


def local_cert(target):
    path = lineage(target) / 'cert.pem'
    if not path.exists():
        return None
    result = subprocess.run(['openssl','x509','-in',str(path),'-noout','-enddate','-fingerprint','-sha256'], check=True, capture_output=True,text=True)
    values = dict(line.split('=',1) for line in result.stdout.splitlines())
    expiry = dt.datetime.strptime(values['notAfter'],'%b %d %H:%M:%S %Y %Z').replace(tzinfo=UTC)
    return {'expires':expiry.isoformat(), 'days':(expiry-dt.datetime.now(UTC)).total_seconds()/86400, 'fingerprint':values.get('sha256 Fingerprint',values.get('SHA256 Fingerprint'))}


def edge_cert(target):
    # Default verification stays enabled, including hostname and certificate dates.
    with socket.create_connection((target['domain'],443),timeout=15) as raw:
        with ssl.create_default_context().wrap_socket(raw,server_hostname=target['domain']) as conn:
            expires = dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(conn.getpeercert()['notAfter']),UTC)
            fingerprint = ':'.join(re.findall('..',hashlib.sha256(conn.getpeercert(binary_form=True)).hexdigest().upper()))
    return {'expires':expires.isoformat(),'fingerprint':fingerprint}


def challenge(config, target, cleanup=False):
    domain = os.environ.get('CERTBOT_DOMAIN')
    token = os.environ.get('CERTBOT_TOKEN','')
    validation = os.environ.get('CERTBOT_VALIDATION','')
    if domain != target['domain'] or (not cleanup and not validation) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}',token):
        raise RuntimeError('invalid_acme_challenge')
    sdk(config,target,'delete' if cleanup else 'put',token=token,validation=validation)
    if cleanup:
        return
    url = 'http://'+domain+'/.well-known/acme-challenge/'+token
    # Only the public challenge uses HTTP, as required by ACME HTTP-01.
    # Certificate/private key material is never sent over HTTP.
    for attempt in range(12):
        try:
            with urllib.request.urlopen(url,timeout=15) as response:
                if response.read().decode() == validation:
                    return
        except (OSError,ValueError):
            pass
        if attempt < 11:
            time.sleep(5)
    raise RuntimeError('public_http01_challenge_not_reachable')


def issue(target):
    info = local_cert(target)
    if info and info['days'] > 30:
        return
    executable = '/usr/local/sbin/lens-cdn-certificate-renewal'
    subprocess.run(['certbot','certonly','--non-interactive','--agree-tos','--register-unsafely-without-email','--preferred-challenges','http','--manual', '--manual-auth-hook',executable+' hook-auth','--manual-cleanup-hook',executable+' hook-cleanup','--key-type','rsa','--rsa-key-size','2048','--cert-name',target['domain'],'-d',target['domain'],'--keep-until-expiring'],check=True,timeout=900)


def sync(config, target, previous):
    info = local_cert(target)
    if not info or info['days'] < 1:
        raise RuntimeError('no_valid_local_certificate')
    try:
        edge = edge_cert(target)
    except (OSError,ssl.SSLError):
        edge = None
    if edge and edge['fingerprint'] == info['fingerprint']:
        return {'status':'healthy','local':info,'edge':edge}
    pem = (lineage(target)/'fullchain.pem').read_text()
    private_key = (lineage(target)/'privkey.pem').read_text()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_cert_chain(str(lineage(target)/'fullchain.pem'),str(lineage(target)/'privkey.pem'))
    # Retry propagation without repeatedly uploading identical certificates.
    deployed = previous.get('deployed_fingerprint')
    if deployed != info['fingerprint']:
        if target['provider'] == 'aliyun':
            sdk(config,target,'aliyun-api',action='SetCdnDomainSSLCertificate', params={'DomainName':target['domain'],'SSLProtocol':'on','CertType':'upload','CertName':'lens-acme-'+hashlib.sha256(pem.encode()).hexdigest()[:16],'SSLPub':pem,'SSLPri':private_key})
        else:
            current = volc(target,'DescribeCdnConfig',{'Domain':target['domain']})
            # Preserve all existing HTTPS controls; change only certificate binding.
            https = current.get('DomainConfig',current).get('HTTPS')
            if not https or not https.get('Switch'):
                raise RuntimeError('existing_https_configuration_missing')
            result = volc(target,'AddCertificate',{'Source':'volc_cert_center','CertType':'server_cert','Certificate':pem.replace('\n','\r\n'),'PrivateKey':private_key.replace('\n','\r\n'),'EncryType':'inter_cert','Repeatable':True,'Desc':'lens-acme-'+target['domain']})
            cert_id = result.get('CertId')
            if not cert_id:
                raise RuntimeError('certificate_upload_returned_no_id')
            https['CertInfo'] = {'CertId':cert_id}
            volc(target,'UpdateCdnConfig',{'Domain':target['domain'],'HTTPS':https})
        deployed = info['fingerprint']
    return {'status':'propagating','local':info,'deployed_fingerprint':deployed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=['run','issue','check','hook-auth','hook-cleanup'])
    parser.add_argument('--domain')
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    domains = config['domains']
    if args.command.startswith('hook-'):
        target = next(t for t in domains if t['domain']==os.environ.get('CERTBOT_DOMAIN'))
        challenge(config,target,args.command=='hook-cleanup')
        return
    if args.domain:
        domains = [t for t in domains if t['domain']==args.domain]
        if not domains:
            raise RuntimeError('unknown_domain')
    STATE.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with open(STATE.parent/'lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.exists() else {'domains':{}}
        failed = False
        for target in domains:
            domain = target['domain']
            try:
                if args.command in ['run','issue']:
                    issue(target)
                if args.command == 'run':
                    item = sync(config,target,state['domains'].get(domain,{}))
                elif args.command == 'check':
                    item = {'status':'healthy','local':local_cert(target),'edge':edge_cert(target)}
                else:
                    item = {'status':'issued','local':local_cert(target)}
            except Exception as error:
                item = {**state['domains'].get(domain,{}),'status':'failed','error':str(error) if isinstance(error,RuntimeError) else type(error).__name__}
                failed = True
            item['checked_at'] = dt.datetime.now(UTC).isoformat()
            state['domains'][domain] = item
            print(json.dumps({'domain':domain,**item}),flush=True)
        tmp = STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(state,indent=2)+'\n')
        os.chmod(tmp,0o600)
        tmp.replace(STATE)
        if failed:
            sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('certificate_automation_failed:'+type(error).__name__,file=sys.stderr)
        sys.exit(1)
