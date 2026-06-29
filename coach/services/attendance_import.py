"""CoachHub-first attendance: Týmuj CSV/Excel import (manual migration path).

Pure-stdlib (no pandas/openpyxl). The uploaded file is parsed entirely in
memory and never persisted. Spreadsheet content is treated as untrusted text:
formulas are ignored (cached values only), emails/phones are never stored.

Pipeline: parse_attendance_file -> build_import_preview (no writes) ->
confirm_import (writes, with source/overwrite rules) -> optional rollback_import.
"""
import csv
import io
import json
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime

from coach.extensions import db
from coach.models import AttendanceEntry, AttendanceImport, Player, TrainingEvent
from coach.services import tymuj as tymuj_svc

# ---- sources + overwrite priority --------------------------------------
SOURCE_COACH = 'coachhub_coach'
SOURCE_PLAYER = 'coachhub_player'
SOURCE_IMPORT = 'tymuj_import'
SOURCE_SYSTEM = 'system'
SOURCE_PRIORITY = {SOURCE_COACH: 3, SOURCE_PLAYER: 2, SOURCE_IMPORT: 1, SOURCE_SYSTEM: 0}
SOURCE_LABELS = {
    SOURCE_COACH: 'CoachHub Coach',
    SOURCE_PLAYER: 'CoachHub Player',
    SOURCE_IMPORT: 'Týmuj Import',
    SOURCE_SYSTEM: 'System',
}
COACHHUB_SOURCES = (SOURCE_COACH, SOURCE_PLAYER)
STATUSES = ('going', 'not_going', 'maybe', 'unknown')

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_COLS = 400

_EMAIL_RE = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')
_PHONE_RE = re.compile(r'(?<!\d)(?:\+?\d[\d \-]{7,}\d)(?!\d)')
_DATE_RE = re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{2,4})?')
_TIME_RE = re.compile(r'\b(\d{1,2}):(\d{2})\b')

# raw cell text (normalized) -> canonical status
_STATUS_MAP = {
    'going': 'going', 'ano': 'going', 'yes': 'going', 'y': 'going', 'present': 'going',
    'jde': 'going', 'prijde': 'going', 'pojede': 'going', 'ucast': 'going', '1': 'going',
    'v': 'going', 'true': 'going', '✓': 'going', '✔': 'going',
    'not_going': 'not_going', 'ne': 'not_going', 'no': 'not_going', 'n': 'not_going',
    'absent': 'not_going', 'nejde': 'not_going', 'neprijde': 'not_going', 'omluven': 'not_going',
    'omluvena': 'not_going', 'omluveno': 'not_going', '0': 'not_going', 'false': 'not_going',
    '✗': 'not_going', '✘': 'not_going', 'x': 'not_going',
    'maybe': 'maybe', 'mozna': 'maybe', 'snad': 'maybe', 'mozno': 'maybe',
    'unknown': 'unknown', 'neznamo': 'unknown', 'nevyplneno': 'unknown', 'neodpovedel': 'unknown',
    '?': 'unknown', '-': 'unknown', '': 'unknown',
}


class AttendanceImportError(ValueError):
    """Raised for invalid/oversized/unreadable upload files."""


def _norm(s):
    s = unicodedata.normalize('NFKD', (s or '')).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(s.lower().split())


def _is_formula(cell):
    return isinstance(cell, str) and cell[:1] in ('=', '+', '@') and len(cell) > 1


def _sanitize_cell(cell):
    """Untrusted text -> safe text. Neutralizes formulas, drops emails/phones."""
    if cell is None:
        return ''
    s = str(cell).replace('\x00', '').strip()
    if _is_formula(s):
        s = s.lstrip('=+@-').strip()        # never evaluated; treat as plain text
    s = _EMAIL_RE.sub('', s)
    s = _PHONE_RE.sub('', s)
    return ' '.join(s.split())


def map_status(cell):
    """Map a (sanitized) cell to a canonical status; unknown if unrecognized."""
    raw = (cell or '').strip()
    # tick/cross symbols are stripped by ascii-normalization, so check them first
    for sym, st in (('✓', 'going'), ('✔', 'going'), ('✗', 'not_going'), ('✘', 'not_going')):
        if raw == sym:
            return st
    n = _norm(cell)
    if not n:
        return 'unknown'
    return _STATUS_MAP.get(n, 'unknown')


# ----------------------------- file readers -----------------------------
def _decode_text(data):
    for enc in ('utf-8-sig', 'utf-8', 'cp1250', 'iso-8859-2'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')


def _read_csv(data):
    text = _decode_text(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except Exception:
        class _D(csv.Dialect):
            delimiter = ';' if sample.count(';') >= sample.count(',') else ','
            quotechar = '"'; doublequote = True; skipinitialspace = True
            lineterminator = '\n'; quoting = csv.QUOTE_MINIMAL
        dialect = _D
    grid = []
    for i, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i >= MAX_ROWS:
            break
        grid.append([_sanitize_cell(c) for c in row[:MAX_COLS]])
    return grid


_XLSX_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def _col_to_idx(ref):
    m = re.match(r'([A-Z]+)', ref or '')
    if not m:
        return None
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _read_xlsx(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        raise AttendanceImportError('Soubor není platný XLSX.')
    names = zf.namelist()
    # shared strings
    shared = []
    if 'xl/sharedStrings.xml' in names:
        if zf.getinfo('xl/sharedStrings.xml').file_size <= 16 * 1024 * 1024:
            root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in root.findall('%ssi' % _XLSX_NS):
                shared.append(''.join(t.text or '' for t in si.iter('%st' % _XLSX_NS)))
    # first worksheet
    sheet_name = next((n for n in names if re.match(r'xl/worksheets/sheet\d+\.xml$', n)), None)
    if not sheet_name:
        raise AttendanceImportError('XLSX neobsahuje žádný list.')
    if zf.getinfo(sheet_name).file_size > 32 * 1024 * 1024:
        raise AttendanceImportError('XLSX list je příliš velký.')
    root = ET.fromstring(zf.read(sheet_name))
    grid = []
    for r_i, row in enumerate(root.iter('%srow' % _XLSX_NS)):
        if r_i >= MAX_ROWS:
            break
        cells = {}
        for c in row.findall('%sc' % _XLSX_NS):
            ci = _col_to_idx(c.get('r', ''))
            if ci is None or ci >= MAX_COLS:
                continue
            t = c.get('t')
            v = c.find('%sv' % _XLSX_NS)            # cached value only; <f> ignored
            if t == 's' and v is not None and v.text is not None:
                try:
                    val = shared[int(v.text)]
                except (ValueError, IndexError):
                    val = ''
            elif t == 'inlineStr':
                isn = c.find('%sis' % _XLSX_NS)
                val = ''.join(tt.text or '' for tt in isn.iter('%st' % _XLSX_NS)) if isn is not None else ''
            else:
                val = v.text if (v is not None and v.text is not None) else ''
            cells[ci] = _sanitize_cell(val)
        width = (max(cells) + 1) if cells else 0
        grid.append([cells.get(i, '') for i in range(width)])
    return grid


def _grid_from_file(filename, data):
    if not data:
        raise AttendanceImportError('Soubor je prázdný.')
    if len(data) > MAX_FILE_BYTES:
        raise AttendanceImportError('Soubor je příliš velký (limit %d B).' % MAX_FILE_BYTES)
    name = (filename or '').lower()
    if name.endswith('.xlsx') or data[:2] == b'PK':
        return _read_xlsx(data), 'xlsx'
    if name.endswith('.csv') or name.endswith('.txt') or b',' in data[:4096] or b';' in data[:4096]:
        return _read_csv(data), 'csv'
    if name.endswith('.xls'):
        raise AttendanceImportError('Starý formát .xls není podporován. Ulož jako .xlsx nebo .csv.')
    raise AttendanceImportError('Nepodporovaný typ souboru. Použij CSV nebo XLSX.')


# ----------------------------- date/title parsing -----------------------
def _parse_event_header(text):
    """Extract (date_iso|None, time|'', title) from an event-column header."""
    t = (text or '').strip()
    if not t:
        return None, '', ''
    d_iso = None
    m = _DATE_RE.search(t)
    if m:
        if m.group(1):
            y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            da, mo = int(m.group(4)), int(m.group(5))
            y = int(m.group(6)) if m.group(6) else 0
            if y and y < 100:
                y += 2000
        try:
            if y:
                d_iso = date(y, mo, da).isoformat()
        except ValueError:
            d_iso = None
    tm = ''
    mt = _TIME_RE.search(t)
    if mt:
        tm = '%02d:%s' % (int(mt.group(1)), mt.group(2))
    title = _DATE_RE.sub(' ', t)
    title = _TIME_RE.sub(' ', title)
    title = re.sub(r'^[\s,;:\-–]+|[\s,;:\-–]+$', '', ' '.join(title.split()))
    return d_iso, tm, title


def _looks_like_name(cell):
    s = (cell or '').strip()
    if not s or len(s) > 60:
        return False
    if map_status(s) != 'unknown':
        return False
    if _DATE_RE.search(s) or _TIME_RE.search(s):
        return False
    n = _norm(s)
    if n in ('celkem', 'total', 'soucet', 'suma', 'jmeno', 'hrac', 'player', 'name', 'datum'):
        return False
    return any(ch.isalpha() for ch in s)


# ----------------------------- layout detection -------------------------
def parse_attendance_file(filename, data):
    """Parse an uploaded attendance file into a normalized, JSON-serializable
    dict. Never writes anything. Raises AttendanceImportError on bad files."""
    grid, file_type = _grid_from_file(filename, data)
    grid = [r for r in grid if any((c or '').strip() for c in r)]
    if not grid:
        raise AttendanceImportError('Soubor neobsahuje žádná data.')
    warnings = []

    # header row = the row with the most date-like cells in columns >=1 (else row 0)
    best_h, best_dates = 0, -1
    for i in range(min(6, len(grid))):
        dates = sum(1 for c in grid[i][1:] if _DATE_RE.search(c or ''))
        if dates > best_dates:
            best_h, best_dates = i, dates
    header_idx = best_h if best_dates > 0 else 0
    header = grid[header_idx]

    # name column = leftmost column where the majority of below-header cells are names
    name_col, best_score = 0, -1
    for col in range(min(3, max((len(r) for r in grid), default=1))):
        score = sum(1 for r in grid[header_idx + 1:] if col < len(r) and _looks_like_name(r[col]))
        if score > best_score:
            name_col, best_score = col, score

    # event columns (everything right of the name column with a non-empty header)
    events = []
    for col in range(name_col + 1, len(header)):
        raw = (header[col] or '').strip()
        if not raw:
            continue
        d_iso, tm, title = _parse_event_header(raw)
        events.append({'col': col, 'idx': len(events), 'raw': raw,
                       'date': d_iso, 'time': tm, 'title': title or raw})

    # players + cells
    players, cells = [], []
    dated_event_cols = {e['col'] for e in events}
    col_to_eidx = {e['col']: e['idx'] for e in events}
    counts = {s: 0 for s in STATUSES}
    mapped_cells = 0
    for r in grid[header_idx + 1:]:
        if name_col >= len(r):
            continue
        name = (r[name_col] or '').strip()
        if not _looks_like_name(name):
            continue
        p_idx = len(players)
        players.append({'idx': p_idx, 'name': name[:100]})
        for col in dated_event_cols:
            if col >= len(r):
                continue
            st = map_status(r[col])
            counts[st] += 1
            if st != 'unknown':
                mapped_cells += 1
                cells.append({'p': p_idx, 'e': col_to_eidx[col], 'status': st})

    dated = sum(1 for e in events if e['date'])
    if dated < len(events):
        warnings.append('%d událostí bez rozpoznaného data (nelze importovat).' % (len(events) - dated))
    if not players:
        warnings.append('Nepodařilo se rozpoznat žádné hráče.')
    if not cells:
        warnings.append('Nepodařilo se rozpoznat žádné hodnoty docházky.')
    total_data_cells = max(1, len(players) * max(1, len(events)))
    confidence = round(min(1.0, (mapped_cells / total_data_cells) * 0.6
                          + (dated / max(1, len(events))) * 0.4), 2)
    return {
        'file_type': file_type,
        'events': events,
        'players': players,
        'cells': cells,
        'counts': counts,
        'warnings': warnings,
        'confidence': confidence,
    }


# ----------------------------- preview (no writes) ----------------------
def _classify_player(name, existing):
    import difflib
    nt = _norm(name)
    tokens = set(nt.split())
    best, best_ratio = None, 0.0
    for p in existing:
        npn = _norm(p.name)
        if nt and (nt == npn or (tokens and tokens == set(npn.split()))):
            return 'exists', p
        ratio = difflib.SequenceMatcher(None, nt, npn).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, p
    if best_ratio >= 0.82:
        return 'similar', best
    return 'new', None


def _match_event(team_id, ev, local_events, tymuj_keys):
    """Return (match_kind, event_key|None, label). kinds: local|tymuj|new|unmatched."""
    if not ev.get('date'):
        return 'unmatched', None, ev.get('raw')
    d = ev['date']
    nt = _norm(ev.get('title') or '')
    for le in local_events:
        if le.day.isoformat() == d and (not nt or _norm(le.title or '').find(nt) >= 0 or nt.find(_norm(le.title or '')) >= 0):
            return 'local', 'local:%d' % le.id, '%s %s' % (d, le.title or '')
    for k in tymuj_keys.get(d, []):
        # tymuj_keys[date] = list of (key, title)
        kt = _norm(k[1])
        if not nt or kt.find(nt) >= 0 or nt.find(kt) >= 0:
            return 'tymuj', k[0], '%s %s' % (d, k[1])
    return 'new', None, '%s %s %s' % (d, ev.get('time') or '', ev.get('title') or '')


def build_import_preview(team_id, parsed):
    """Build a full preview WITHOUT any DB writes."""
    existing_players = Player.query.filter_by(team_id=team_id).all()
    local_events = TrainingEvent.query.filter_by(team_id=team_id).all()
    # cached tymuj events grouped by date for matching
    tymuj_keys = {}
    payload_events = (tymuj_svc._cache_payload(team_id).get('events') or [])
    for it in payload_events:
        d = it.get('day')
        if not d:
            continue
        k = tymuj_svc.make_event_key(it.get('title') or '', date.fromisoformat(d),
                                     it.get('time') or '', it.get('kind') or 'training', 'tymuj')
        tymuj_keys.setdefault(d, []).append((k, it.get('title') or ''))

    players_view = []
    for p in parsed['players']:
        kind, match = _classify_player(p['name'], existing_players)
        players_view.append({
            'idx': p['idx'], 'name': p['name'], 'kind': kind,
            'match_id': match.id if match else None,
            'match_name': match.name if match else None,
            'default_action': ('merge:%d' % match.id) if match else 'create',
        })
    events_view = []
    for ev in parsed['events']:
        kind, key, label = _match_event(team_id, ev, local_events, tymuj_keys)
        events_view.append({
            'idx': ev['idx'], 'raw': ev['raw'], 'date': ev['date'], 'time': ev['time'],
            'title': ev['title'], 'kind': kind, 'match_key': key, 'label': label,
            'default_action': ('use:%s' % key) if key else ('create' if ev['date'] else 'ignore'),
        })
    summary = {
        'players_total': len(players_view),
        'players_existing': sum(1 for p in players_view if p['kind'] == 'exists'),
        'players_similar': sum(1 for p in players_view if p['kind'] == 'similar'),
        'players_new': sum(1 for p in players_view if p['kind'] == 'new'),
        'events_total': len(events_view),
        'events_local': sum(1 for e in events_view if e['kind'] == 'local'),
        'events_tymuj': sum(1 for e in events_view if e['kind'] == 'tymuj'),
        'events_new': sum(1 for e in events_view if e['kind'] == 'new'),
        'events_unmatched': sum(1 for e in events_view if e['kind'] == 'unmatched'),
        'attendance_total': len(parsed['cells']),
        'counts': parsed['counts'],
        'confidence': parsed['confidence'],
        'warnings': parsed['warnings'],
    }
    return {'players': players_view, 'events': events_view, 'summary': summary}


# ----------------------------- confirm (writes) -------------------------
def confirm_import(team_id, parsed, player_decisions, event_decisions, *,
                   role='coach', overwrite_imported=False, filename=None):
    """Apply an import. player_decisions[idx] / event_decisions[idx] are strings:
      players: 'create' | 'ignore' | 'merge:<player_id>'
      events:  'create' | 'ignore' | 'use:<event_key>'
    Never overwrites CoachHub attendance. Returns the AttendanceImport batch."""
    now = datetime.utcnow()
    batch = AttendanceImport(team_id=team_id, created_by_role=role, source=SOURCE_IMPORT,
                             file_type=parsed.get('file_type'), filename=(filename or None),
                             created_at=now, status='completed')
    db.session.add(batch)
    db.session.flush()                       # get batch.id
    warnings = list(parsed.get('warnings') or [])
    players_created = events_created = imported = skipped = overwritten = 0

    # resolve players idx -> player_id (or None if ignored)
    p_resolved = {}
    for p in parsed['players']:
        dec = (player_decisions.get(str(p['idx'])) or player_decisions.get(p['idx']) or 'create')
        if dec == 'ignore':
            continue
        if isinstance(dec, str) and dec.startswith('merge:'):
            try:
                pid = int(dec.split(':', 1)[1])
            except ValueError:
                pid = None
            if pid and Player.query.filter_by(id=pid, team_id=team_id).first():
                p_resolved[p['idx']] = pid
            continue
        # create
        pl = Player(team_id=team_id, name=p['name'][:100], position='F')
        db.session.add(pl)
        db.session.flush()
        p_resolved[p['idx']] = pl.id
        players_created += 1

    # resolve events idx -> (event_key, meta)
    ev_by_idx = {e['idx']: e for e in parsed['events']}
    e_resolved = {}
    for ev in parsed['events']:
        dec = (event_decisions.get(str(ev['idx'])) or event_decisions.get(ev['idx']) or '')
        if dec == 'ignore' or not dec:
            continue
        if isinstance(dec, str) and dec.startswith('use:'):
            e_resolved[ev['idx']] = (dec.split(':', 1)[1], ev)
            continue
        if dec == 'create':
            if not ev.get('date'):
                continue
            te = TrainingEvent(team_id=team_id, day=date.fromisoformat(ev['date']),
                               time=(ev.get('time') or '')[:10], title=(ev.get('title') or 'Trénink')[:200],
                               kind='training')
            db.session.add(te)
            db.session.flush()
            e_resolved[ev['idx']] = ('local:%d' % te.id, ev)
            events_created += 1

    # write attendance cells
    for cell in parsed['cells']:
        pid = p_resolved.get(cell['p'])
        ev_res = e_resolved.get(cell['e'])
        if not pid or not ev_res:
            skipped += 1
            continue
        ev_key, ev = ev_res
        status = cell['status']
        if status not in ('going', 'not_going', 'maybe'):
            skipped += 1
            continue
        existing = AttendanceEntry.query.filter_by(team_id=team_id, player_id=pid, event_key=ev_key).first()
        if existing:
            if existing.source in COACHHUB_SOURCES:
                skipped += 1                 # never overwrite CoachHub attendance
                continue
            if not overwrite_imported:
                skipped += 1
                continue
            existing.status = status
            existing.source = SOURCE_IMPORT
            existing.source_detail = str(batch.id)
            existing.updated_by_role = role
            existing.imported_at = now
            existing.updated_at = now
            overwritten += 1
            continue
        entry = AttendanceEntry(
            team_id=team_id, player_id=pid, event_key=ev_key, status=status,
            event_title=(ev.get('title') or '')[:200],
            event_day=date.fromisoformat(ev['date']) if ev.get('date') else now.date(),
            event_time=(ev.get('time') or '')[:10],
            event_kind='training',
            event_source=('tymuj' if ev_key and not ev_key.startswith('local:') else 'local'),
            source=SOURCE_IMPORT, source_detail=str(batch.id), updated_by_role=role,
            imported_at=now, updated_at=now,
        )
        db.session.add(entry)
        imported += 1

    batch.players_created = players_created
    batch.events_created = events_created
    batch.attendance_imported = imported
    batch.skipped = skipped
    batch.overwritten = overwritten
    batch.warnings = json.dumps(warnings, ensure_ascii=False)
    db.session.commit()
    return batch


def rollback_import(team_id, batch_id):
    """Delete attendance rows created by an import batch (only its own
    tymuj_import rows; CoachHub rows are untouched). Created players/events are
    left in place (see limitations). Returns number of rows removed."""
    batch = AttendanceImport.query.filter_by(id=batch_id, team_id=team_id).first()
    if not batch:
        return 0
    rows = AttendanceEntry.query.filter_by(team_id=team_id, source=SOURCE_IMPORT,
                                           source_detail=str(batch_id)).all()
    n = len(rows)
    for r in rows:
        db.session.delete(r)
    batch.status = 'rolled_back'
    db.session.commit()
    return n


# ----------------------------- stats / diagnostics ----------------------
def source_breakdown(team_id=None):
    q = db.session.query(AttendanceEntry.source, db.func.count(AttendanceEntry.id))
    if team_id:
        q = q.filter(AttendanceEntry.team_id == team_id)
    counts = {s: 0 for s in SOURCE_PRIORITY}
    for src, n in q.group_by(AttendanceEntry.source).all():
        counts[src or SOURCE_SYSTEM] = n
    return counts


def recent_imports(team_id=None, limit=20):
    q = AttendanceImport.query
    if team_id:
        q = q.filter_by(team_id=team_id)
    return q.order_by(AttendanceImport.created_at.desc()).limit(limit).all()
