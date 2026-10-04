#!/usr/bin/env python3
import json, re, html, os, sys, threading, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# FUT.GG Gallery parser (P0 / K3+K4+R2).
#
# Page detection uses two UNESCAPED signals:
#   * the <title> contains "FUT Gallery Set:" (singular + colon)  -> a SET page
#   * the body still contains the unescaped "Grade requirements & rewards" marker
# Index / category pages use "FUT Gallery Sets:" (plural) and have no grade table;
# they are rejected with a machine-readable `reason` code.
#
# slots + eligibility are read from the <meta name="description"> first (it states
# "Requires 15 Malaga CF Mens players ..."), falling back to the page body.
# A page that states no number (e.g. TOTW: "Requires Team of the Week players")
# falls back to an index oracle and is flagged `slotsEstimated: true`.
#
# Rewards come from the grade table rows: only rows carrying a `gallery-token`
# image yield a token count; Badge/Kit rows yield 0 plus a `rewardText`.
# ---------------------------------------------------------------------------

GRADE_ORDER = 'DCBAS'  # weakest -> strongest

# Index oracle: slot counts for sets whose page states no explicit number.
# Only used when neither description nor body provides a number.
INDEX_ORACLE_SLOTS = {
    'totw': 20,
    'team of the week': 20,
}

# Page-detection reason codes (machine-readable).
R_OK = None
R_INDEX_PAGE = 'index_page'          # "FUT Gallery Sets:" (plural), no grade table
R_NOT_A_SET_PAGE = 'not_a_set_page'  # neither set title nor grade marker
R_NOT_FUTGG = 'not_futgg'            # wrong host / path
R_NO_GRADE_TABLE = 'no_grade_table'  # set-like title but no parsable rows


def strip_tags(raw):
    """HTML -> comparable plain text (entities unescaped, whitespace collapsed)."""
    raw = re.sub(r'(?is)<script[^>]*>.*?</script>', ' ', raw)
    raw = re.sub(r'(?is)<style[^>]*>.*?</style>', ' ', raw)
    raw = re.sub(r'(?i)<br\s*/?>', '\n', raw)
    raw = re.sub(r'(?i)</(?:p|div|li|tr|td|th|h1|h2|h3|h4)>', '\n', raw)
    raw = re.sub(r'(?s)<[^>]+>', ' ', raw)
    raw = html.unescape(raw)
    lines = [re.sub(r'\s+', ' ', x).strip() for x in raw.splitlines()]
    return '\n'.join(x for x in lines if x)


def unescaped(raw):
    """Only html.unescape -- for marker checks that must survive &amp;."""
    return html.unescape(raw)


def page_title(raw):
    m = re.search(r'(?is)<title[^>]*>(.*?)</title>', raw)
    return strip_tags(m.group(1)).strip() if m else ''


def meta_description(raw):
    m = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]*content=["\'](.*?)["\']', raw)
    if not m:
        m = re.search(r'(?is)<meta[^>]+content=["\'](.*?)["\'][^>]*name=["\']description["\']', raw)
    return html.unescape(m.group(1)).strip() if m else ''


def detect_page(raw, url):
    """Return (kind, reason).

    kind is 'set' for a Gallery set page; otherwise None with a reason code.
    Both signals are evaluated on the UNESCAPED html.
    """
    if 'fut.gg/fut-gallery/' not in url:
        return None, R_NOT_FUTGG
    u = unescaped(raw)
    marker = 'Grade requirements & rewards' in u
    title = page_title(raw)
    # Singular + colon == set page; plural ("Sets:") is an index/category page.
    is_set_title = re.search(r'FUT Gallery Set:', title) is not None
    if is_set_title and marker:
        return 'set', R_OK
    if re.search(r'FUT Gallery Sets:', title) or (not is_set_title):
        # category/index page (or something else entirely)
        if re.search(r'FUT Gallery Sets:', title):
            return None, R_INDEX_PAGE
        return None, R_NOT_A_SET_PAGE
    # set-like title but missing the grade marker
    return None, R_NO_GRADE_TABLE


def parse_grade_table(raw):
    """Row-based parse of the grade table.

    Returns {grade: {'threshold': int, 'reward': int, 'rewardText': str}} for the
    rows found. A row is recognised by its data-gallery-reward="X" attribute.
    Threshold = the numeric score inside the row (comma separators removed).
    Reward = the integer before "Gallery Tokens" ONLY if the row carries a
    gallery-token image; otherwise 0 with the human label as rewardText (H6).
    """
    out = {}
    for m in re.finditer(r'(?is)<tr\b[^>]*data-gallery-reward=["\']([DCBAS])["\'][^>]*>(.*?)</tr>', raw):
        g = m.group(1).upper()
        row = m.group(2)
        row_text = strip_tags(row)
        # score threshold: first integer in the row text. The grade letter itself
        # is not numeric, and the "grading score" title text is stripped above.
        th = 0
        nums = re.findall(r'(\d[\d,]*)', row_text.replace('grading score', ''))
        if nums:
            th = int(nums[0].replace(',', ''))
        # reward: only a gallery-token image makes the row pay out tokens.
        has_token_img = re.search(r'gallery-token', row) is not None
        reward, reward_text = 0, ''
        if has_token_img:
            rt = re.search(r'([\d,]+)\s*Gallery Tokens?', row_text, re.I)
            if rt:
                reward = int(rt.group(1).replace(',', ''))
            reward_text = '{} Gallery Tokens'.format(reward) if reward else ''
        else:
            # Badge / Kit or other non-token reward -> keep the human label.
            # Prefer the reward image's alt text (class-independent), else the
            # last non-numeric text fragment in the row.
            alt = re.search(r'(?is)<img[^>]+alt=["\']([^"\']+)["\']', row)
            if alt and alt.group(1).strip().lower() not in ('grading score',):
                reward_text = html.unescape(alt.group(1)).strip()
            else:
                for frag in reversed(row_text.split('\n')):
                    frag = frag.strip()
                    if frag and not frag.isdigit() and 'grading score' not in frag.lower():
                        reward_text = frag
                        break
        out[g] = {'threshold': th, 'reward': reward, 'rewardText': reward_text}
    return out


def parse_requirements(text):
    """Extract (slots, scope, gender) from a "Requires ... players" sentence.

    slots is None when the sentence carries no leading number.

    The scope is bounded to a short, sentence-like phrase: FUT.GG also embeds a
    large JSON/RSC blob containing tag descriptions such as
    "Requires players from the same nation." -- those must NOT be mistaken for
    the set requirement, so the scope may not contain sentence punctuation or
    run past a clause boundary.
    """
    # Canonical numbered form: "Requires 15 Malaga CF Mens players to complete"
    m = re.search(r'Requires\s+(\d[\d,]*)\s+([^."\n<>{}]{1,60}?)\s+players\s+to\s+complete', text, re.I)
    if m:
        slots = int(m.group(1).replace(',', ''))
        scope = m.group(2).strip()
    else:
        # Numberless form: "Requires Team of the Week players to complete"
        m = re.search(r'Requires\s+([^."\n<>{}]{1,60}?)\s+players\s+to\s+complete', text, re.I)
        if not m:
            return None, '', 'any'
        slots, scope = None, m.group(1).strip()
    low = scope.lower()
    if 'women' in low:
        gender = 'women'
    elif 'men' in low:
        gender = 'men'
    else:
        gender = 'any'
    return slots, scope, gender


def _norm_key(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def parse_futgg(raw, url):
    """Parse a FUT.GG Gallery SET page into the app's gallery shape.

    Raises ValueError(reason) for anything that is not a set page.
    """
    kind, reason = detect_page(raw, url)
    if kind != 'set':
        raise ValueError(reason or R_NOT_A_SET_PAGE)

    title = page_title(raw)
    m = re.search(r'(.+?)\s+FUT Gallery Set:', title)
    name = m.group(1).strip() if m else ''
    if not name:
        name = url.rstrip('/').split('/')[-1].replace('-', ' ').title()

    # --- slots + eligibility: description first, body second, oracle third ---
    desc = meta_description(raw)
    body = strip_tags(raw)
    slots, scope, gender = parse_requirements(desc)
    slots_estimated = False
    source = 'description'
    if slots is None:
        slots, scope, gender = parse_requirements(body)
        source = 'body'
    if slots is None:
        oracle = INDEX_ORACLE_SLOTS.get(_norm_key(name))
        if oracle:
            slots, slots_estimated, source = oracle, True, 'oracle'
        else:
            slots, slots_estimated, source = 15, True, 'default'

    # --- eligibility type from the URL shape ---
    if '/leagues/' in url:
        etype, evalue = 'league', name
    elif '/rarities/' in url:
        etype, evalue = 'rarity', re.sub(r'\s*Set$', '', name)
        gender = 'any'
    else:
        etype, evalue = 'club', name

    # --- grade table ---
    table = parse_grade_table(raw)
    if not table:
        raise ValueError(R_NO_GRADE_TABLE)
    thresholds = {g: table.get(g, {}).get('threshold', 0) for g in GRADE_ORDER}
    rewards = {g: table.get(g, {}).get('reward', 0) for g in GRADE_ORDER}
    reward_text = {g: table.get(g, {}).get('rewardText', '') for g in GRADE_ORDER}

    return {
        'id': re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_'),
        'name': name,
        'slots': slots,
        'slotsEstimated': slots_estimated,
        'slotsSource': source,
        'eligibility': {'type': etype, 'value': evalue, 'gender': gender},
        'thresholds': thresholds,
        'rewards': rewards,
        'rewardText': reward_text,
        'sourceUrl': url,
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
            except ValueError as e:
                # Not a set page: 422 with a machine-readable reason code.
                data = json.dumps({'error':'not_a_set_page','reason':str(e)}).encode()
                self.send_response(422)
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
