from datetime import datetime, timedelta
import os
from flask import current_app
from coach.models import TrainingSession, LineupSession


def cleanup_exports(retention_days: int = 14):
    """Remove orphaned export PDFs older than retention from EXPORT_FOLDER.
    Keeps files referenced by TrainingSession or LineupSession.
    """
    export_dir = current_app.config['EXPORT_FOLDER']
    try:
        os.makedirs(export_dir, exist_ok=True)
        # Collect referenced filenames from DB
        referenced = set(s.filename for s in TrainingSession.query.all())
        try:
            for s in LineupSession.query.all():
                referenced.add(s.filename)
        except Exception:
            # If LineupSession table isn't available yet, ignore
            pass
        cutoff = datetime.now() - timedelta(days=retention_days)
        for fname in os.listdir(export_dir):
            if not fname.lower().endswith('.pdf'):
                continue
            fpath = os.path.join(export_dir, fname)
            try:
                st = os.stat(fpath)
                mtime = datetime.fromtimestamp(st.st_mtime)
            except Exception:
                continue
            if fname in referenced:
                continue
            if mtime < cutoff:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    except Exception:
        # Fail silently; cleanup is best-effort
        return
