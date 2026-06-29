import json
from datetime import datetime

from flask import request

from coach.extensions import db
from coach.models import AuditEvent


def _truncate_ip(ip: str) -> str:
    try:
        parts = (ip or '').split('.')
        return '.'.join(parts[:3] + ['0']) if len(parts) == 4 else (ip or '-')
    except Exception:
        return '-'


def log_event(event: str, *, team_id=None, role=None, level='info', message='', meta=None):
    payload = {'level': level, 'message': (message or '')[:500]}
    if meta:
        payload.update({k: v for k, v in meta.items() if k not in {'password', 'key', 'secret', 'token'}})
    try:
        ip = _truncate_ip(getattr(request, 'remote_addr', None) or '-')
    except Exception:
        ip = '-'
    try:
        db.session.add(AuditEvent(
            event=event[:50],
            team_id=team_id,
            role=role,
            ip_truncated=ip,
            meta=json.dumps(payload, ensure_ascii=False, default=str),
            created_at=datetime.utcnow(),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def recent_events(limit=100, prefix=None):
    q = AuditEvent.query
    if prefix:
        q = q.filter(AuditEvent.event.like(prefix + '%'))
    return q.order_by(AuditEvent.created_at.desc()).limit(limit).all()
