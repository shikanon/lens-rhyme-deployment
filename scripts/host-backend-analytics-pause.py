#!/usr/bin/env python3
"""Reviewed, single-backend rollout on the existing LensRhyme host; plan by default."""
from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

SERVICES = ('backend', 'frontend', 'admin-frontend', 'content-frontend', 'docs-site',
            'codex-runner-manager', 'seo-generation-worker', 'seo-publication-worker')
SCHEMA = '20261018_0132'
SITE_SHA = 'f41e356ef286317aef47ee526315ea41586e119fa09c9bd54b534ef03c662651'
SNIPPET_SHA = 'e9aaee87491c10caf5a5185c39ff5f3a147ef71086dc0ebba66d0bfbdc6edfaf'
IMAGE_RE = re.compile(r'docker.io/shikanon096/lens-rhyme-backend@sha256:[0-9a-f]{64}')


class PauseFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise PauseFailure(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(path):
    path = Path(path)
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    require((before.st_ino, before.st_mtime_ns, before.st_size) ==
            (after.st_ino, after.st_mtime_ns, after.st_size), 'File changed while reading')
    require(stat.S_ISREG(after.st_mode), 'Expected regular file')
    return {'sha256': digest(data), 'realpath': str(path.resolve()),
            'mode': stat.S_IMODE(after.st_mode)}


def atomic_install(path, data, mode=0o600):
    """Install complete bytes without ever replacing a concurrent file/symlink."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def atomic_replace(path, data, expected_sha256, mode=0o600):
    path = Path(path)
    require(not path.is_symlink(), 'Refusing mutable symlink')
    require(fingerprint(path)['sha256'] == expected_sha256, 'File CAS mismatch')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(fingerprint(path)['sha256'] == expected_sha256, 'File changed before replacement')
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def override_text(image):
    require(IMAGE_RE.fullmatch(image), 'Only immutable LensRhyme backend digest accepted')
    return 'services:\n  backend:\n    image: ' + image + '\n'


def only_backend_image_changed(before, after, image):
    expected = copy.deepcopy(before)
    require('backend' in expected.get('services', {}), 'Backend missing from Compose')
    expected['services']['backend']['image'] = image
    require(after == expected, 'Compose differs outside backend.image')


def patch_backend_upstream(data, new_ip):
    require(ipaddress.ip_address(new_ip).version == 4, 'Expected backend IPv4')
    text = data.decode('utf-8')
    active = re.sub(r'#[^\n]*', lambda match: ' ' * len(match.group()), text)
    blocks = list(re.finditer(r'\bupstream\s+BACKEND_UPSTREAM\s*\{([^{}]*)\}', active))
    require(len(blocks) == 1, 'Expected one BACKEND_UPSTREAM block')
    block = blocks[0]
    servers = list(re.finditer(r'\bserver\s+([0-9.]+):8000(?=\s*;)', block.group(1)))
    require(len(servers) == 1 and len(re.findall(r'\bserver\s+', block.group(1))) == 1,
            'Expected one backend server line')
    server = servers[0]
    start = block.start(1) + server.start(1)
    end = block.start(1) + server.end(1)
    return (text[:start] + new_ip + text[end:]).encode()


@dataclasses.dataclass
class Paths:
    root: Path = Path('/root/lens-rhyme-deployment-seo-20260924-0400aca')
    site: Path = Path('/etc/nginx/sites-enabled/lensrhyme.conf')
    snippet: Path = Path('/etc/nginx/snippets/lensrhyme-analytics-collection-paused.conf')
    upstreams: Path = Path('/etc/nginx/docker-upstreams.conf')

    def inputs(self):
        return (self.root / '.env', self.root / '.release.env',
                self.root / 'compose/docker-compose.yml',
                self.root / 'compose/docker-compose.override.yml',
                self.site, self.snippet, self.upstreams)


class Host:
    def __init__(self, paths=None):
        self.paths = paths or Paths()

    def command(self, args, input_text=None):
        try:
            result = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PauseFailure('Command unavailable: ' + type(exc).__name__) from None
        require(result.returncode == 0, 'Command failed (details withheld to protect runtime secrets)')
        return result.stdout

    def prefix(self):
        root = self.paths.root
        return ['docker', 'compose', '--project-name', 'compose', '--project-directory',
                str(root / 'compose'), '--env-file', str(root / '.env'), '--env-file',
                str(root / '.release.env'), '-f', str(root / 'compose/docker-compose.yml'),
                '-f', str(root / 'compose/docker-compose.override.yml')]

    def compose_config(self, override_text=None):
        args = self.prefix()
        if override_text is not None:
            args += ['-f', '-']
        # Returned environment values stay in process memory, never the receipt.
        return json.loads(self.command(args + ['config', '--format', 'json'], override_text))

    def compose_hash(self, override_text=None):
        args = self.prefix()
        if override_text is not None:
            args += ['-f', '-']
        output = self.command(args + ['config', '--hash', 'backend'], override_text)
        match = re.fullmatch(r'\s*backend\s+([0-9a-f]{64})\s*', output)
        require(match is not None, 'Compose native backend hash unavailable')
        return match.group(1)

    def image_info(self, image):
        require(IMAGE_RE.fullmatch(image), 'Invalid backend image')
        fmt = ('{"id":{{json .Id}},"digests":{{json .RepoDigests}},'
               '"architecture":{{json .Architecture}},"os":{{json .Os}},'
               '"source":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
               '"component":{{json (index .Config.Labels "com.lensrhyme.component")}}}')
        result = json.loads(self.command(['docker', 'image', 'inspect', '--format', fmt, image]))
        canonical = image.removeprefix('docker.io/')
        require(any(v.removeprefix('docker.io/') == canonical for v in result.get('digests') or []),
                'Local image repository digest mismatch; never pulling implicitly')
        require(result.get('component') == 'backend', 'Image component mismatch')
        require(result.get('architecture') == 'amd64' and result.get('os') == 'linux',
                'Expected production Linux/amd64 image')
        require(re.fullmatch('[0-9a-f]{40}', str(result.get('source') or '')), 'Image source missing')
        return result

    def containers(self):
        fmt = ('{"id":{{json .Id}},"image":{{json .Config.Image}},'
               '"source":{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
               '"started_at":{{json .State.StartedAt}},"status":{{json .State.Status}},'
               '"config_hash":{{json (index .Config.Labels "com.docker.compose.config-hash")}},'
               '"config_files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}}}')
        return {service: json.loads(self.command(['docker', 'inspect', '--format', fmt,
                                                  'compose-' + service + '-1'])) for service in SERVICES}

    def schema(self):
        # No application/settings imports; the existing DSN never leaves the container.
        program = """import json,os,psycopg
c=psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=5,options='-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000')
try:
 r=c.execute('SELECT version_num FROM alembic_version ORDER BY version_num').fetchall()
 print(json.dumps([str(v[0]) for v in r]))
finally:
 c.rollback();c.close()
"""
        # This unchanged worker uses the same database and remains available if
        # the candidate API container cannot start or accept docker exec.
        result = json.loads(self.command(['docker', 'exec', '-i', 'compose-seo-publication-worker-1',
                                          'python', '-'], program))
        require(result == [SCHEMA], 'Database schema does not equal reviewed 0132 head')
        return result[0]

    def state(self):
        files = {str(path): fingerprint(path) for path in self.paths.inputs()}
        require(files[str(self.paths.site)]['sha256'] == SITE_SHA, 'Edge site guard drift')
        require(files[str(self.paths.snippet)]['sha256'] == SNIPPET_SHA, 'Edge snippet guard drift')
        if self.paths == Paths():
            require(files[str(self.paths.site)]['realpath'] == '/etc/nginx/sites-available/lensrhyme.conf',
                    'Host vhost realpath drift')
        pid = self.command(['systemctl', 'show', 'nginx', '--property=MainPID', '--value']).strip()
        require(pid.isdigit() and int(pid) > 0, 'Nginx master unavailable')
        return {'files': files, 'containers': self.containers(), 'schema': self.schema(), 'main_pid': int(pid)}

    def switch(self, override_path):
        self.command(self.prefix() + ['-f', str(override_path), 'up', '-d', '--no-deps',
                                     '--no-build', '--pull', 'never', 'backend'])

    def backend_ip(self):
        networks = json.loads(self.command(['docker', 'inspect', '--format',
                                           '{{json .NetworkSettings.Networks}}', 'compose-backend-1']))
        require(len(networks) == 1, 'Expected one existing backend network')
        value = next(iter(networks.values()))['IPAddress']
        require(ipaddress.ip_address(value).version == 4, 'Backend address unavailable')
        return value

    def http_checks(self, expect_empty):
        program = """import json,time,urllib.request
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
opener=urllib.request.build_opener(NoRedirect)
for attempt in range(16):
 try:
  with opener.open('http://127.0.0.1:8000/readyz',timeout=2) as r:
   if r.status==200: break
 except Exception:
  if attempt==15: raise
  time.sleep(2)
out={}
for path in ['/healthz','/readyz','/api/v1/public/analytics-config','/api/v1/public/analytics-config?pause_check=1']:
 with opener.open('http://127.0.0.1:8000'+path,timeout=5) as r:
  out[path]={'status':r.status,'body':json.loads(r.read(4096)),'cache_control':r.headers.get('Cache-Control'),'content_type':r.headers.get('Content-Type')}
print(json.dumps(out))
"""
        result = json.loads(self.command(['docker', 'exec', '-i', 'compose-backend-1', 'python', '-'], program))
        require(result['/healthz']['status'] == result['/readyz']['status'] == 200, 'Backend not ready')
        require(result['/readyz']['body'].get('checks', {}).get('schema') == 'head', 'Readiness schema failed')
        if expect_empty:
            for path in ('/api/v1/public/analytics-config', '/api/v1/public/analytics-config?pause_check=1'):
                item = result[path]
                require(item['status'] == 200 and item['body'] == {'measurement_id': ''}
                        and item['cache_control'] == 'no-store'
                        and str(item['content_type']).split(';')[0] == 'application/json',
                        'Direct backend pause contract failed')
        return result

    def refresh_upstream(self, expected_fingerprint, new_ip):
        path = self.paths.upstreams
        require(fingerprint(path) == expected_fingerprint, 'Upstream CAS mismatch')
        before = path.read_bytes()
        require(digest(before) == expected_fingerprint['sha256'], 'Upstream changed after CAS')
        after = patch_backend_upstream(before, new_ip)
        if before == after:
            return fingerprint(path)
        original = path.stat()
        atomic_replace(path, after, digest(before), stat.S_IMODE(original.st_mode))
        os.chown(path, original.st_uid, original.st_gid)
        tested = False
        try:
            self.command(['nginx', '-t'])
            tested = True
            self.command(['systemctl', 'reload', 'nginx'])
        except PauseFailure:
            atomic_replace(path, before, digest(after), stat.S_IMODE(original.st_mode))
            os.chown(path, original.st_uid, original.st_gid)
            if tested:
                self.command(['nginx', '-t'])
                self.command(['systemctl', 'reload', 'nginx'])
            raise
        return fingerprint(path)


def make_plan(host, image, revision):
    override_text(image)
    require(re.fullmatch('[0-9a-f]{40}', revision), 'Expected full approved source SHA')
    metadata = host.image_info(image)
    require(metadata['source'] == revision, 'Candidate source revision mismatch')
    before = host.state()
    require(all(v['status'] == 'running' for v in before['containers'].values()), 'Existing service not running')
    expected_files = [str(host.paths.root / 'compose/docker-compose.yml'),
                      str(host.paths.root / 'compose/docker-compose.override.yml')]
    require(all(v.get('config_files', '').split(',') == expected_files
                for v in before['containers'].values()),
            'Runtime Compose files differ from reviewed two-file scope')
    old = before['containers']['backend']
    require(old['image'] != image, 'Backend already uses candidate; no rollout needed')
    old_metadata = host.image_info(old['image'])
    require(old_metadata['source'] == old['source'], 'Rollback image source mismatch')
    initial = host.compose_config()
    require(initial['services']['backend']['image'] == old['image'], 'Base Compose backend differs from runtime')
    base_hash = host.compose_hash()
    require(old.get('config_hash') == base_hash, 'Base Compose differs from running backend config hash')
    candidate = host.compose_config(override_text(image))
    only_backend_image_changed(initial, candidate, image)
    candidate_hash = host.compose_hash(override_text(image))
    # Bind the caller-visible state after potentially slow Compose inspection too.
    require(host.state() == before, 'Runtime changed during planning')
    return {'schema_version': 1, 'image': image, 'revision': revision, 'before': before,
            'candidate_metadata': metadata, 'rollback_metadata': old_metadata,
            'compose_native_base_hash': base_hash, 'compose_native_candidate_hash': candidate_hash,
            'compose_before_sha256': digest(json.dumps(initial, sort_keys=True).encode()),
            'compose_candidate_sha256': digest(json.dumps(candidate, sort_keys=True).encode())}


def ensure_others(before, after, upstreams):
    require(before['schema'] == after['schema'] == SCHEMA, 'Schema drift')
    require(before['main_pid'] == after['main_pid'], 'Nginx master changed')
    for service in SERVICES[1:]:
        require(before['containers'][service] == after['containers'][service], 'Non-backend runtime changed')
    for path, value in before['files'].items():
        if path != str(upstreams):
            require(after['files'][path] == value, 'Compose/environment/guard file drift')


def write_receipt(directory, receipt, expected_sha256=None):
    path = Path(directory) / 'receipt.json'
    data = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
    if expected_sha256 is None:
        atomic_install(path, data)
    else:
        atomic_replace(path, data, expected_sha256)
    return digest(data)


def restore_backend(host, plan, directory, expected):
    """Rollback only a container installed from this release's exact override."""
    current = host.state()
    require(current == expected, 'Runtime drift before rollback; manual recovery required')
    before = plan['before']
    ensure_others(before, current, host.paths.upstreams)
    override = Path(directory) / 'backend-only.override.yml'
    installed = current['containers']['backend']
    require(installed['image'] == plan['image'] and str(override) in installed['config_files'].split(','),
            'Current backend is not owned by this rollout')
    require(host.image_info(before['containers']['backend']['image']) == plan['rollback_metadata'],
            'Rollback image metadata drift')
    installed_override = override_text(plan['image']).encode()
    require(override.read_bytes() == installed_override, 'Override ownership drift')
    require(host.compose_hash(override_text(before['containers']['backend']['image'])) ==
            plan['compose_native_base_hash'], 'Rollback Compose native hash drift')
    atomic_replace(override, override_text(before['containers']['backend']['image']).encode(),
                   digest(installed_override))
    host.switch(override)
    switched = host.state()
    ensure_others(before, switched, host.paths.upstreams)
    require(switched['containers']['backend']['image'] == before['containers']['backend']['image'],
            'Rollback backend image mismatch')
    require(switched['containers']['backend'].get('config_hash') == plan['compose_native_base_hash'],
            'Rollback container native config hash mismatch')
    owned_upstream = host.refresh_upstream(current['files'][str(host.paths.upstreams)], host.backend_ip())
    checks = host.http_checks(False)
    final = host.state()
    ensure_others(before, final, host.paths.upstreams)
    require(final['files'][str(host.paths.upstreams)] == owned_upstream,
            'Concurrent upstream modification after rollback')
    require(final['containers']['backend'].get('config_hash') == plan['compose_native_base_hash'],
            'Rollback config hash changed during verification')
    return {'state': final, 'direct_backend': checks}


def apply(host, plan, release_dir):
    require(make_plan(host, plan['image'], plan['revision']) == plan, 'Reviewed plan CAS mismatch')
    directory = Path(release_dir)
    require(directory.is_absolute() and not directory.is_symlink(), 'Expected absolute private release directory')
    directory.mkdir(mode=0o700)  # Existing directory is never reused or overwritten.
    override = directory / 'backend-only.override.yml'
    atomic_install(directory / 'reviewed-plan.json', (json.dumps(plan, indent=2) + '\n').encode())
    upstream_bytes = host.paths.upstreams.read_bytes()
    require(digest(upstream_bytes) == plan['before']['files'][str(host.paths.upstreams)]['sha256'],
            'Upstream changed before backup')
    atomic_install(directory / 'upstreams.before', upstream_bytes)
    atomic_install(override, override_text(plan['image']).encode())
    receipt = {'status': 'prepared', 'plan': plan, 'release_dir': str(directory), 'effects': [],
               'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    receipt_hash = write_receipt(directory, receipt)
    # Repeat complete metadata/config/runtime CAS after preparation and before any service mutation.
    require(make_plan(host, plan['image'], plan['revision']) == plan, 'State changed before backend replacement')
    owned_upstream = plan['before']['files'][str(host.paths.upstreams)]
    try:
        host.switch(override)
        receipt['effects'].append('backend-only compose up')
        current = host.state()
        ensure_others(plan['before'], current, host.paths.upstreams)
        require(current['containers']['backend']['image'] == plan['image'], 'Installed backend image mismatch')
        require(current['containers']['backend'].get('config_hash') == plan['compose_native_candidate_hash'],
                'Installed backend native config hash mismatch')
        require(current['files'][str(host.paths.upstreams)] == owned_upstream,
                'Concurrent upstream modification before refresh')
        owned_upstream = host.refresh_upstream(owned_upstream, host.backend_ip())
        checks = host.http_checks(True)
        after = host.state()
        ensure_others(plan['before'], after, host.paths.upstreams)
        require(after['files'][str(host.paths.upstreams)] == owned_upstream,
                'Concurrent upstream modification after refresh')
        require(after['containers']['backend'].get('config_hash') == plan['compose_native_candidate_hash'],
                'Candidate config hash changed during verification')
        receipt.update(status='applied', after=after, direct_backend=checks)
    except Exception as exc:
        receipt['error_type'] = type(exc).__name__  # Never persist raw stderr/env/DSN.
        try:
            state = host.state()
            require(state['files'][str(host.paths.upstreams)] == owned_upstream,
                    'Upstream ownership lost; manual recovery required')
            if state == plan['before']:
                receipt['status'] = 'failed_original_runtime_retained'
            else:
                receipt['rollback'] = restore_backend(host, plan, directory, state)
                receipt['status'] = 'failed_rolled_back'
        except Exception as recovery:
            receipt.update(status='failed_manual_recovery_required', recovery_error_type=type(recovery).__name__)
        receipt['completed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        write_receipt(directory, receipt, receipt_hash)
        raise PauseFailure('Apply failed: ' + receipt['status']) from None
    receipt['completed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_receipt(directory, receipt, receipt_hash)
    return receipt


def rollback(host, receipt, release_dir):
    directory = Path(release_dir)
    require(receipt.get('status') == 'applied' and receipt['release_dir'] == str(directory),
            'Expected successful receipt for this release directory')
    receipt_path = directory / 'receipt.json'
    stored_receipt = receipt_path.read_bytes()
    require(json.loads(stored_receipt) == receipt, 'Receipt changed before rollback')
    result = restore_backend(host, receipt['plan'], directory, receipt['after'])
    updated = {**receipt, 'status': 'rolled_back', 'rollback': result}
    write_receipt(directory, updated, digest(stored_receipt))
    return updated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    parser.add_argument('--image')
    parser.add_argument('--revision')
    parser.add_argument('--plan-file', type=Path)
    parser.add_argument('--expected-plan-sha256')
    parser.add_argument('--receipt-file', type=Path)
    parser.add_argument('--expected-receipt-sha256')
    parser.add_argument('--release-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        host = Host()
        if args.apply:
            require(args.plan_file and args.release_dir, '--apply requires reviewed --plan-file and --release-dir')
            data = args.plan_file.read_bytes()
            require(digest(data) == args.expected_plan_sha256, 'Caller-reviewed plan hash mismatch')
            result = apply(host, json.loads(data), args.release_dir)
        elif args.rollback:
            require(args.receipt_file and args.release_dir, '--rollback requires --receipt-file and --release-dir')
            data = args.receipt_file.read_bytes()
            require(digest(data) == args.expected_receipt_sha256, 'Caller-reviewed receipt hash mismatch')
            result = rollback(host, json.loads(data), args.release_dir)
        else:
            require(args.image and args.revision, 'Plan requires --image and --revision')
            result = make_plan(host, args.image, args.revision)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (PauseFailure, OSError, ValueError, KeyError):
        print(json.dumps({'status': 'stopped', 'reason': 'Precondition or operation failed; inspect private receipt if created. No raw command error is printed.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
