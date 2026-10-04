#!/usr/bin/env python3
import datetime
import json, re, html, os, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Schema / provenance constants (P2).
#
# The saved state carries a schemaVersion; every import from FUT.GG is stored as
# a DATED snapshot (fetchedAt) so dynamic values -- above all PRICES -- are never
# treated as timeless. See migrate_state() and price_snapshot().
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 2                 # current on-disk state schema
SCHEMA_VERSION_MIN = 1             # oldest schema we can still migrate from


def utc_now_iso():
    """Current UTC time as an ISO-8601 'Z' string (the snapshot timestamp)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace('+00:00', 'Z')


# ---------------------------------------------------------------------------
# Canonical ALIAS layer (P2.2).
#
# FUT.GG and legacy saved data spell the same concept several ways ("Team of the
# Week" vs "TOTW"; "Hero"/"Heroes" vs "Heroic"; "Holographics" vs "Holographic").
# A single canonical map keeps imports, migration and the engine (which mirrors
# this map in JS `norm()`) consistent. Pure functions -- no I/O.
# ---------------------------------------------------------------------------
ALIASES = {
    'team of the week': 'totw',
    'heroes': 'heroic',
    'hero': 'heroic',
    'holographics': 'holographic',
    'holographic': 'holographic',
}
# Club suffixes/prefixes dropped so "Malaga CF" == "Malaga CF" == "malaga".
CLUB_NOISE = re.compile(r'\b(fc|cf|sc|ac|afc|club|de futbol|futbol)\b')


def _strip_accents(s):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def canonical_name(s):
    """Canonicalise a name/token for tolerant comparison (accents + aliases).

    Mirrors the engine's JS `norm()` alias handling so server-side migration and
    client-side eligibility agree on equality. Never returns None.
    """
    if s is None:
        return ''
    t = _strip_accents(str(s).lower().strip())
    if t in ALIASES:
        return ALIASES[t]
    t = CLUB_NOISE.sub(' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def canonical_type(s):
    """Canonicalise an eligibility/special TYPE token (e.g. 'Hero' -> 'heroic')."""
    return canonical_name(s)


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


# ---------------------------------------------------------------------------
# TTL fetch cache (P2.3).
#
# FUT.GG pages are expensive to fetch and change slowly; a bounded TTL cache
# serves repeat imports without hitting the network. The clock is injectable so
# tests are deterministic (no sleeps). Thread-safe: the HTTP server is threaded.
# ---------------------------------------------------------------------------
class TTLCache:
    def __init__(self, ttl_seconds, max_items, clock=time.monotonic):
        self.ttl = float(ttl_seconds)
        self.max = int(max_items)
        self._clock = clock
        self._store = {}          # key -> (inserted_at, value)
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            rec = self._store.get(key)
            if not rec:
                return None
            inserted, value = rec
            if self._clock() - inserted >= self.ttl:
                del self._store[key]        # expired
                return None
            return value

    def put(self, key, value):
        with self._lock:
            # Evict the oldest insertion when full (bounded growth).
            if key not in self._store and len(self._store) >= self.max:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (self._clock(), value)

    def clear(self):
        with self._lock:
            self._store.clear()

    def __len__(self):
        return len(self._store)


# ---------------------------------------------------------------------------
# Price snapshots (P2.4).
#
# Prices are DYNAMIC: they must always be stored with the moment they were read,
# never as a timeless number. price_snapshot() wraps a raw number (or returns the
# existing snapshot unchanged) so migration and import cannot silently freeze a
# price as a constant.
# ---------------------------------------------------------------------------
PRICE_FIELDS = ('buyPrice', 'resalePrice')


def price_snapshot(value, fetched_at=None, source=None):
    """Normalise a price into a DATED snapshot.

    Canonical shape::

        {'value': <base>, 'priceUpdatedAt': <iso>, 'source': <str>,
         'best': <opt>, 'worst': <opt>}

    * None / '' / 'null' -> None (no price is not a price of 0)
    * an existing snapshot dict is returned with missing meta filled in
    * a raw number (or numeric string) becomes a fresh snapshot

    `fetchedAt` is still written when the input already used that spelling, so
    P2.4-era saves stay readable; new snapshots use `priceUpdatedAt`.
    """
    if isinstance(value, dict):
        snap = dict(value)
        stamp = fetched_at or utc_now_iso()
        # Prefer the P2 field, backfill both so old/new readers agree.
        snap.setdefault('priceUpdatedAt', snap.get('fetchedAt') or stamp)
        snap.setdefault('fetchedAt', snap.get('priceUpdatedAt'))
        snap.setdefault('source', source)
        # best/worst default to base so a plain snapshot is scenario-complete.
        base = snap.get('value')
        snap.setdefault('best', base)
        snap.setdefault('worst', base)
        return snap
    if value is None or value == '':
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    stamp = fetched_at or utc_now_iso()
    return {'value': num, 'priceUpdatedAt': stamp, 'fetchedAt': stamp,
            'source': source, 'best': num, 'worst': num}


def price_value(value):
    """Read the numeric value out of a price (snapshot dict or raw number)."""
    if isinstance(value, dict):
        return value.get('value')
    return value


# ---------------------------------------------------------------------------
# Price SCENARIOS + staleness (P2.10).
#
# A price snapshot may carry a scenario spread so the optimizer can reason about
# uncertainty instead of a single point estimate:
#   * `base`  -- the value we would normally use
#   * `best`  -- the optimistic value  (lowest BUY, highest RESALE)
#   * `worst` -- the conservative value (highest BUY, lowest RESALE)
#
# Only `base` is mandatory; `best`/`worst` default to `base` so a plain snapshot
# behaves exactly as before. `scenario_value()` resolves the active scenario and
# `price_stale()` flags a snapshot older than `max_age`.
# ---------------------------------------------------------------------------
PRICE_SCENARIOS = ('best', 'base', 'worst')
# 30 days: a price older than this is surfaced as a staleness warning, not hidden.
PRICE_MAX_AGE_SECONDS = 30 * 24 * 3600


def scenario_value(value, scenario='base'):
    """Resolve a price (snapshot or bare number) under a named scenario.

    Falls back to `base`, then to the bare value, so an unknown scenario never
    raises -- it degrades to base.
    """
    if scenario not in PRICE_SCENARIOS:
        scenario = 'base'
    if isinstance(value, dict):
        for key in (scenario, 'base', 'value'):
            v = value.get(key)
            if v is not None:
                return v
        return None
    return value


def price_updated_at(value):
    """The timestamp a price was read, or None for a bare number.

    Accepts the P2 field name `priceUpdatedAt` (preferred) and the earlier
    `fetchedAt` (kept for backward compatibility with P2.4 snapshots).
    """
    if isinstance(value, dict):
        return value.get('priceUpdatedAt') or value.get('fetchedAt')
    return None


def price_source(value):
    """Where a price came from ('manual', 'fut.gg', ...), or None."""
    return value.get('source') if isinstance(value, dict) else None


def price_stale(value, max_age_seconds=PRICE_MAX_AGE_SECONDS, now=None):
    """True when a snapshot is older than `max_age_seconds`.

    A bare number has no timestamp -> treated as unknown age, NOT stale (the
    import/merge layer is responsible for stamping); this keeps the check
    additive and never blocks legacy data.
    """
    ts = price_updated_at(value)
    if not ts:
        return False
    when = _parse_iso(ts)
    if when is None:
        return False
    ref = now if now is not None else datetime.datetime.now(datetime.timezone.utc)
    return (ref - when).total_seconds() > max_age_seconds


def _parse_iso(ts):
    """Parse an ISO-8601 timestamp (with trailing 'Z') to an aware datetime."""
    if not isinstance(ts, str) or not ts:
        return None
    s = ts.strip().replace('Z', '+00:00')
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt



# ---------------------------------------------------------------------------
# State schema migration (P2.5).
#
# migrate_state() upgrades a saved state JSON in place (returns a new dict) so an
# old save keeps working after the schema grows. Migration is conservative: it
# only ADDS fields and normalises shared vocabulary (aliases); it never drops or
# rewrites numeric game data. Idempotent (running it twice is a no-op).
# ---------------------------------------------------------------------------
def _migrate_v1_to_v2(state):
    """v1 -> v2: add provenance + dated price snapshots + canonical aliases."""
    for g in state.get('galleries', []) or []:
        g.setdefault('schemaVersion', SCHEMA_VERSION)
        if g.get('sourceUrl') and 'fetchedAt' not in g:
            g['fetchedAt'] = utc_now_iso()
        e = g.get('eligibility')
        if isinstance(e, dict):
            if isinstance(e.get('type'), str):
                e['type'] = canonical_type(e['type'])
            for ids_key in ('ids',):
                if isinstance(e.get(ids_key), list):
                    e[ids_key] = [str(x) for x in e[ids_key]]
    for p in state.get('players', []) or []:
        for k in PRICE_FIELDS:
            if k in p:
                p[k] = price_snapshot(p[k])
        if isinstance(p.get('special'), str):
            p['special'] = canonical_type(p['special'])
        if 'priceFetchedAt' not in p and any(k in p for k in PRICE_FIELDS):
            # a single provenance stamp for the row's prices at migration time
            p['priceFetchedAt'] = utc_now_iso()
    return state


MIGRATIONS = {1: _migrate_v1_to_v2}


def migrate_state(state):
    """Bring a loaded state up to SCHEMA_VERSION. Returns (state, migrated_from).

    Raises ValueError for a schema NEWER than this build (forward-compat guard).
    """
    if not isinstance(state, dict):
        raise ValueError('state must be an object')
    raw = state.get('schemaVersion', 1)
    try:
        version = int(raw)
    except (TypeError, ValueError):
        version = 1
    if version > SCHEMA_VERSION:
        raise ValueError('state schema v%s is newer than this build (v%s)'
                         % (version, SCHEMA_VERSION))
    if version < SCHEMA_VERSION_MIN:
        raise ValueError('state schema v%s is too old to migrate' % version)
    start = version
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ValueError('no migration path from schema v%s' % version)
        state = step(state)
        version += 1
    state['schemaVersion'] = SCHEMA_VERSION
    return state, start


# ---------------------------------------------------------------------------
# Import MERGE with preview/diff + verified/estimated (P2.8).
#
# Importing a snapshot or a FUT.GG set must never SILENTLY overwrite a value the
# user edited by hand. `merge_state` therefore:
#   * computes a per-field DIFF (old -> new) for players + galleries,
#   * marks the SOURCE of each incoming value as `verified` (a trusted/oracle
#     source, e.g. FUT.GG) or `estimated` (derived / incomplete),
#   * flags `manual` rows that would be overwritten, so the UI can ask first.
# The function is pure (no I/O) and returns a preview that the UI renders before
# applying. Applying is a separate, explicit step (`apply_merge`).
# ---------------------------------------------------------------------------
MERGE_VERIFIED_SOURCES = ('fut.gg', 'ea', 'oracle')
# Fields the user is expected to have corrected by hand; overwriting these needs
# confirmation even when the incoming value is `verified`.
MANUAL_GUARD_FIELDS = ('buyPrice', 'resalePrice', 'score', 'itemId')


def _provenance_for(record, source):
    """Return 'verified' or 'estimated' for an incoming record.

    A record is `verified` when its source is a trusted oracle AND it is not
    flagged as partially estimated (`slotsEstimated`/`estimated`); otherwise it
    is `estimated`.
    """
    if isinstance(record, dict) and record.get('slotsEstimated'):
        return 'estimated'
    if isinstance(record, dict) and record.get('estimated'):
        return 'estimated'
    return 'verified' if source in MERGE_VERIFIED_SOURCES else 'estimated'


def _field_changes(old, new, manual_fields=MANUAL_GUARD_FIELDS):
    """Per-field diff of two record dicts -> list of change descriptors.

    Merge semantics are PATCH-like: only fields PRESENT in `new` are candidates
    for change; a key absent from the incoming record means "leave as is", not
    "delete". This matters for the manual guard -- a partial import that omits a
    price must not look like it is overwriting that price.
    """
    changes = []
    for k in sorted(new):
        if k in ('id', 'schemaVersion'):
            continue
        ov, nv = old.get(k), new.get(k)
        if ov == nv:
            continue
        changes.append({
            'field': k,
            'old': ov,
            'new': nv,
            'manualGuard': k in manual_fields and ov not in (None, '', 0),
        })
    return changes


def merge_state(current, incoming, source=None):
    """Preview a merge of `incoming` into `current`. Does NOT mutate inputs.

    Returns::

        {'players': [...], 'galleries': [...], 'summary': {...}}

    Each entry has `status` ('added' | 'changed' | 'unchanged'), `provenance`
    ('verified' | 'estimated'), `changes` (field diffs) and `needsConfirmation`
    (True when a manual-guard field would be overwritten).
    """
    cur = current or {}
    inc = incoming or {}
    out = {'players': [], 'galleries': [], 'summary': {}}

    def index(rows):
        return {str(r.get('id')): r for r in (rows or []) if isinstance(r, dict)}

    for kind in ('players', 'galleries'):
        cur_idx = index(cur.get(kind))
        inc_idx = index(inc.get(kind))
        for rid, new in inc_idx.items():
            old = cur_idx.get(rid)
            prov = _provenance_for(new, source)
            if old is None:
                out[kind].append({'id': rid, 'status': 'added', 'provenance': prov,
                                  'changes': [], 'needsConfirmation': False})
            else:
                changes = _field_changes(old, new)
                if not changes:
                    out[kind].append({'id': rid, 'status': 'unchanged',
                                       'provenance': prov, 'changes': [],
                                       'needsConfirmation': False})
                else:
                    needs = any(c['manualGuard'] for c in changes)
                    out[kind].append({'id': rid, 'status': 'changed',
                                      'provenance': prov, 'changes': changes,
                                      'needsConfirmation': needs})

    s = out['summary']
    for kind in ('players', 'galleries'):
        s[kind + 'Added'] = sum(1 for e in out[kind] if e['status'] == 'added')
        s[kind + 'Changed'] = sum(1 for e in out[kind] if e['status'] == 'changed')
        s[kind + 'Unchanged'] = sum(1 for e in out[kind] if e['status'] == 'unchanged')
    s['estimated'] = sum(1 for kind in ('players', 'galleries')
                         for e in out[kind] if e['provenance'] == 'estimated')
    s['needsConfirmation'] = any(e['needsConfirmation']
                                  for kind in ('players', 'galleries') for e in out[kind])
    s['source'] = source
    return out


def apply_merge(current, incoming, preview, confirm=False):
    """Apply a previously previewed merge. `confirm` must be True to overwrite a
    manual-guarded field; otherwise those entries are skipped and reported.

    Returns (new_state, applied_summary). Pure: returns a new dict.
    """
    import copy
    result = copy.deepcopy(current) if isinstance(current, dict) else {'players': [], 'galleries': []}
    applied = {'applied': 0, 'skipped': 0, 'skippedIds': []}
    inc = incoming or {}
    decision = {}
    for kind in ('players', 'galleries'):
        for e in (preview or {}).get(kind, []):
            decision[(kind, str(e['id']))] = e
    for kind in ('players', 'galleries'):
        rows = {str(r.get('id')): r for r in result.get(kind, []) if isinstance(r, dict)}
        order = [r for r in result.get(kind, [])]
        for new in (inc.get(kind) or []):
            if not isinstance(new, dict):
                continue
            rid = str(new.get('id'))
            e = decision.get((kind, rid), {'status': 'added', 'needsConfirmation': False})
            if e.get('needsConfirmation') and not confirm:
                applied['skipped'] += 1
                applied['skippedIds'].append(rid)
                continue
            if rid in rows:
                rows[rid].update(new)
            else:
                result.setdefault(kind, []).append(dict(new))
                rows[rid] = new
            applied['applied'] += 1
    return result, applied


# ---------------------------------------------------------------------------
# Server hardening (P2.6 + P2.11).
#
# SSRF guard: only https://www.fut.gg/fut-gallery/<...> may be fetched. The URL
# is normalised (no userinfo, no port, no fragment) and must resolve to exactly
# the host www.fut.gg with a path under /fut-gallery/.
#
# P2.11 adds: an ENV kill-switch for the whole importer, a per-client rate limit
# (token bucket), directory-listing containment and `Cache-Control: no-store`
# on API responses.
# ---------------------------------------------------------------------------
ALLOWED_HOST = 'www.fut.gg'
ALLOWED_PATH_PREFIX = '/fut-gallery/'
MAX_FETCH_BYTES = 4 * 1024 * 1024   # 4 MiB cap on a fetched page
FETCH_TIMEOUT = 15

# ENV kill-switch: set FC27_NO_IMPORT=1 (or `true`) to disable the importer
# entirely -- useful on a read-only/mirror deployment. Default: importer ENABLED.
def importer_enabled(env=None):
    """False when the importer is disabled via FC27_NO_IMPORT."""
    e = os.environ if env is None else env
    val = str(e.get('FC27_NO_IMPORT', '')).strip().lower()
    return val not in ('1', 'true', 'yes', 'on')


# Per-client rate limit for /api/futgg (token bucket, in-memory).
# RATE_LIMIT_MAX requests per RATE_LIMIT_WINDOW seconds per client IP.
RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW = 60.0



def is_allowed_futgg_url(url):
    """True only for a well-formed https FUT.GG Gallery URL (SSRF allow-list)."""
    if not isinstance(url, str) or not url:
        return False
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme != 'https':
        return False
    if p.netloc != ALLOWED_HOST:          # exact host, no port, no userinfo
        return False
    if p.username or p.password:
        return False
    if not p.path.startswith(ALLOWED_PATH_PREFIX):
        return False
    if p.fragment:
        return False
    return True


def safe_static_path(base, requested):
    """Resolve a requested static path under `base`, or None if it escapes.

    Blocks traversal (`../`), absolute paths and NUL bytes. Uses realpath so a
    symlink pointing outside the root is also rejected.
    """
    if not isinstance(requested, str) or '\x00' in requested:
        return None
    rel = unquote(requested).lstrip('/')
    if not rel or rel.endswith('/'):
        rel = rel + 'index.html'
    cand = os.path.realpath(os.path.join(base, rel))
    base_real = os.path.realpath(base)
    if cand != base_real and not cand.startswith(base_real + os.sep):
        return None
    return cand


# Global, process-wide cache (5 min TTL, 32 pages).
PAGE_CACHE = TTLCache(ttl_seconds=300, max_items=32)


class RateLimiter:
    """A minimal per-key token-bucket rate limiter (thread-safe).

    `allow(key)` returns True while the bucket has tokens, False once the limit
    is exceeded within the window. `clock` is injectable so tests are
    deterministic (no sleeping).
    """

    def __init__(self, max_requests, window_seconds, clock=time.monotonic):
        self.max = max(1, int(max_requests))
        self.window = float(window_seconds)
        self.clock = clock
        self._hits = {}                 # key -> list of hit timestamps
        self._lock = threading.Lock()

    def allow(self, key):
        now = self.clock()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.max:
                self._hits[key] = hits   # keep the pruned list
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# Process-wide importer rate limiter (per client IP).
IMPORT_LIMITER = RateLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)


def is_directory_request(requested):
    """True when a request targets a directory (not a concrete file).

    We never list directories: a trailing slash (or a path that is a real
    directory on disk) is treated as a directory request and refused.
    """
    if not isinstance(requested, str):
        return False
    path = requested.split('?', 1)[0]
    return path.endswith('/') 


def is_within_base(base, candidate):
    """True when `candidate` (realpath) is `base` or lives underneath it.

    Containment check used for static serving: a resolved path must not escape
    the static root (defeats `..` traversal and absolute paths).
    """
    if not candidate:
        return False
    base_real = os.path.realpath(base)
    cand_real = os.path.realpath(candidate)
    return cand_real == base_real or cand_real.startswith(base_real + os.sep)



class Handler(SimpleHTTPRequestHandler):
    server_version = 'FC27GalleryOptimizer/2'

    # --- hardening: only these verbs exist; everything else -> 405 -----------
    def do_POST(self):
        self.send_error(405, 'Method Not Allowed')

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST
    do_HEAD = do_POST

    def end_headers(self):
        # Hardening headers on every response (no sniffing, no framing).
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def _json(self, code, obj, no_store=True):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        # API responses must never be cached (they carry dated snapshots).
        if no_store:
            self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _fetch(self, url):
        """Fetch a page with the size cap; returns raw text (never None)."""
        req = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Gallery Optimizer; personal use)',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        with urlopen(req, timeout=FETCH_TIMEOUT) as r:
            raw = r.read(MAX_FETCH_BYTES + 1)
        if len(raw) > MAX_FETCH_BYTES:
            raise ValueError('response_too_large')
        return raw.decode('utf-8', 'replace')

    def _api_futgg(self, q):
        # P2.11: ENV kill-switch -- a disabled importer returns 503.
        if not importer_enabled():
            self._json(503, {'error': 'importer_disabled'})
            return
        # P2.11: per-client rate limit (token bucket).
        client = getattr(self, 'client_address', None)
        client = client[0] if client else 'unknown'
        if not IMPORT_LIMITER.allow(client):
            self._json(429, {'error': 'rate_limited'})
            return
        url = (q.get('url') or [''])[0]
        # SSRF allow-list (exact host + path prefix), not a substring check.
        if not is_allowed_futgg_url(url):
            self._json(400, {'error': 'url_not_allowed'})
            return
        hit = PAGE_CACHE.get(url)
        cached = hit is not None
        raw = hit
        try:
            if raw is None:
                raw = self._fetch(url)
                PAGE_CACHE.put(url, raw)
            data = parse_futgg(raw, url)
            # Provenance: every import is a DATED snapshot.
            fetched_at = utc_now_iso()
            data['fetchedAt'] = fetched_at
            data['schemaVersion'] = SCHEMA_VERSION
            data['cached'] = cached
            self._json(200, data)
        except ValueError as e:
            reason = str(e)
            code = 413 if reason == 'response_too_large' else 422
            if reason == 'response_too_large':
                self._json(code, {'error': reason})
            else:
                # Not a set page: 422 with a machine-readable reason code.
                self._json(code, {'error': 'not_a_set_page', 'reason': reason})
        except Exception:
            # Never leak a stack trace to the client.
            self._json(502, {'error': 'upstream_fetch_failed'})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/api/futgg':
            self._api_futgg(parse_qs(u.query))
            return
        if u.path == '/api/health':
            self._json(200, {'ok': True, 'schemaVersion': SCHEMA_VERSION})
            return
        # P2.11: never list a directory -- only a concrete file is served.
        if u.path != '/' and is_directory_request(u.path):
            self.send_error(403, 'Directory listing disabled')
            return
        rel = unquote(u.path)
        resolved = safe_static_path(ROOT, rel)
        # Hardened static serving: reject traversal / absolute escapes and any
        # path that resolves outside the static root (containment).
        if resolved is None or not is_within_base(ROOT, resolved):
            self.send_error(403, 'Forbidden')
            return
        if os.path.isdir(resolved):
            self.send_error(403, 'Directory listing disabled')
            return
        if u.path == '/':
            self.path = '/index.html'
        return super().do_GET()


if __name__ == '__main__':
    os.chdir(ROOT)
    port = int(os.environ.get('PORT', '8765'))
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
