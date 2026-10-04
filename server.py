#!/usr/bin/env python3
import json, re, html, os, sys, threading, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.abspath(__file__))

def clean_text(raw):
    raw = re.sub(r'(?is)<script[^>]*>.*?</script>', ' ', raw)
    raw = re.sub(r'(?is)<style[^>]*>.*?</style>', ' ', raw)
    raw = re.sub(r'(?i)<br\s*/?>', '\n', raw)
    raw = re.sub(r'(?i)</(?:p|div|li|tr|td|th|h1|h2|h3|h4)>', '\n', raw)
    raw = re.sub(r'(?s)<[^>]+>', ' ', raw)
    raw = html.unescape(raw)
    lines = [re.sub(r'\s+', ' ', x).strip() for x in raw.splitlines()]
    return '\n'.join(x for x in lines if x)

def parse_futgg(raw, url):
    text = clean_text(raw)
    title = ''
    m = re.search(r'(?im)^(.+?) FUT Gallery Set$', text)
    if m:
        title = m.group(1).strip()
    if not title:
        m = re.search(r'(?is)<h1[^>]*>(.*?)</h1>', raw)
        if m:
            title = clean_text(m.group(1)).strip()
    slots = 15
    req = ''
    m = re.search(r'Requires\s+(\d+)\s+(.+?)\s+players\s+to\s+complete', text, re.I)
    if m:
        slots = int(m.group(1))
        req = m.group(2).strip()

    thresholds = {g: 0 for g in 'DCBAS'}
    rewards = {g: 0 for g in 'DCBAS'}
    sec = text.split('Grade requirements & rewards', 1)[-1]
    for g in 'DCBAS':
        mm = re.search(r'(?:^|\n)'+g+r'\n(?:[^\n]*\n){0,4}?([\d,]+)', sec, re.I|re.M)
        if mm:
            thresholds[g] = int(mm.group(1).replace(',', ''))
        rr = re.search(r'\b'+g+r'\b[\s\S]{0,180}?([\d,]+)\s+Gallery Tokens?', sec, re.I)
        if rr:
            rewards[g] = int(rr.group(1).replace(',', ''))
    if thresholds['D'] == 0:
        thresholds['D'] = 10

    gender = 'any'
    lower = req.lower()
    if 'women' in lower:
        gender = 'women'
    elif 'men' in lower:
        gender = 'men'

    name = title or url.rstrip('/').split('/')[-1].replace('-', ' ').title()
    eligibility = {'type':'club', 'value':name, 'gender':gender}
    if '/leagues/' in url:
        eligibility = {'type':'league', 'value':name, 'gender':gender}
    if '/rarities/' in url:
        eligibility = {'type':'rarity', 'value':name.replace(' Set',''), 'gender':'any'}

    return {
        'id': re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_'),
        'name': name,
        'slots': slots,
        'eligibility': eligibility,
        'thresholds': thresholds,
        'rewards': rewards,
        'sourceUrl': url
    }

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = super().translate_path(path)
        rel = os.path.relpath(p, os.getcwd())
        return os.path.join(ROOT, rel)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/api/futgg':
            q = parse_qs(u.query)
            url = (q.get('url') or [''])[0]
            if not url.startswith('https://www.fut.gg/fut-gallery/'):
                self.send_error(400, 'Only FUT.GG Gallery URLs are allowed')
                return
            try:
                req = Request(url, headers={
                    'User-Agent':'Mozilla/5.0 (Gallery Optimizer; personal use)',
                    'Accept-Language':'en-US,en;q=0.9'
                })
                with urlopen(req, timeout=15) as r:
                    raw = r.read().decode('utf-8', 'replace')
                data = json.dumps(parse_futgg(raw, url)).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                data = json.dumps({'error':str(e)}).encode()
                self.send_response(502)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            return
        if u.path == '/':
            self.path = '/index.html'
        return super().do_GET()

if __name__ == '__main__':
    os.chdir(ROOT)
    port = int(os.environ.get('PORT','8765'))
    host = os.environ.get('HOST') or ('0.0.0.0' if os.environ.get('PORT') else '127.0.0.1')
    httpd = ThreadingHTTPServer((host, port), Handler)
    display_host = '127.0.0.1' if host == '0.0.0.0' else host
    print(f'FC 27 Gallery Optimizer running at {host}:{port}')
    if '--no-open' not in sys.argv and host != '0.0.0.0':
        threading.Timer(.6, lambda: webbrowser.open(f'http://{display_host}:{port}')).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
