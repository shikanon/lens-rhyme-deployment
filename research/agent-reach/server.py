"""Bounded HTTP adapter for Agent-Reach's public Exa and Jina channels.
No shell execution, user sessions, cookie extraction or arbitrary MCP tools.
"""
import hashlib
import ipaddress
import json
import re
import socket
import threading
import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from agent_reach.channels.web import WebChannel, _is_antibot_page

REVISION = 'a19a171fa980a0785849596492e0af4db800c82f'
MAX_BYTES = 1_000_000
SLOTS = threading.BoundedSemaphore(2)


def public_url(url, domains):
    p = urlsplit(url)
    if (len(url) > 2048 or p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in (None, 443) or p.hostname not in domains):
        raise ValueError('Source URL is outside the public HTTPS policy')
    addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Source host is not public')
    return url


def search(query):
    # Agent-Reach routes to upstream tools directly. This is the same named Exa
    # MCP tool documented in its search reference, called over HTTP, not a shell.
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'web_search_exa', 'arguments': {'query': query, 'numResults': 8,
                                               'contextMaxCharacters': 12000}}}
    with requests.post('https://mcp.exa.ai/mcp', json=body, headers={
            'Accept': 'application/json, text/event-stream'}, timeout=(5, 20), stream=True) as response:
        response.raise_for_status()
        raw = response.raw.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Search response too large')
    decoded = raw.decode()
    if decoded.lstrip().startswith('{'):
        result = json.loads(decoded)
    else:
        messages = [json.loads(line[6:]) for line in decoded.splitlines() if line.startswith('data: ')]
        result = next((m for m in messages if m.get('id') == 1), {})
    payload = result.get('result', {})
    if result.get('error') or payload.get('isError'):
        raise ValueError('Exa MCP search failed')
    snippets = '\n'.join(c.get('text', '') for c in payload.get('content', []) if c.get('type') == 'text')
    # Search summaries/dates are discovery only, never trusted article evidence.
    results = []
    for match in re.finditer(r'Title:\s*([^\n]+)\nURL:\s*(https://[^\s]+)', snippets):
        results.append({'title': match[1][:300], 'url': match[2], 'engine': 'agent-reach-exa'})
    return {'results': results[:8], 'partialFailures': [], 'channel': 'exa_search', 'upstream_revision': REVISION}


def read(url, domains):
    public_url(url, domains)
    content = WebChannel().read(url)
    if _is_antibot_page(content.encode()) or any(s in content[:2000].lower() for s in (
            'warning: target url returned error', 'captcha', 'access denied', 'checking your browser')):
        raise ValueError('Upstream reader returned an error or challenge')
    source = re.search(r'^URL Source:\s*(\S+)', content, re.M)
    if not source:
        raise ValueError('Reader did not identify its original source')
    final = source[1]
    public_url(final, domains)
    title = re.search(r'^Title:\s*(.+)', content, re.M)
    markdown = content.split('Markdown Content:', 1)[-1].strip()
    # Main-heading trim removes site navigation; a research model sees article
    # content rather than a long creative suite navigation menu.
    heading = re.search(r'(?m)^#{1,2} [^\n]+|^[^\n]+\n={3,}\s*$', markdown)
    if heading:
        markdown = markdown[heading.start():]
    if len(markdown) < 100 or not heading:
        raise ValueError('Reader returned navigation without article content')
    return {'url': url, 'finalUrl': final, 'title': title[1] if title else '',
            'content': markdown[:12000], 'contentHash': hashlib.sha256(content.encode()).hexdigest(),
            'channel': 'web', 'upstream_revision': REVISION}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # No remote query text or credential-bearing errors in logs.

    def send(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.send(200 if self.path == '/health' else 404, {'status': 'ok', 'revision': REVISION,
                  'channels': ['exa_search', 'web'], 'authenticated_channels': 'disabled'})

    def do_POST(self):
        if not SLOTS.acquire(blocking=False):
            return self.send(429, {'status': 'error', 'code': 'BUSY'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16000:
                raise ValueError('Invalid payload size')
            data = json.loads(self.rfile.read(size))
            if self.path == '/search':
                query = data.get('query')
                if not isinstance(query, str) or not 1 <= len(query) <= 600:
                    raise ValueError('Invalid query')
                value = search(query)
            elif self.path == '/fetch-web':
                domains = data.get('allowed_domains')
                if not isinstance(domains, list) or not 1 <= len(domains) <= 50 or not all(isinstance(d, str) for d in domains):
                    raise ValueError('Invalid domain policy')
                value = read(data.get('url', ''), set(domains))
            else:
                return self.send(404, {'status': 'error', 'code': 'UNKNOWN_TOOL'})
            self.send(200, {'status': 'ok', 'data': value})
        except Exception as exc:
            self.send(502, {'status': 'error', 'code': type(exc).__name__})
        finally:
            SLOTS.release()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 3211), Handler).serve_forever()
