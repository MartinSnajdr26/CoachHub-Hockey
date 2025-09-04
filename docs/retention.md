Naplánování mazání neaktivních uživatelů
======================================

Spuštění via Flask CLI:

```
FLASK_APP=coach.app:app flask retention:prune --days 365
```

Cron příklad (měsíčně, 1. den v 03:00):

```
0 3 1 * * /path/to/venv/bin/flask retention:prune --days 365 >> /var/log/coach_retention.log 2>&1
```

Poznámky:
- Příkaz maže uživatele bez přihlášení nebo s posledním přihlášením starším než zadaný počet dní.
- Týmoví administrátoři (is_team_admin) se nemažou.
- Odstranění osobních artefaktů je zatím no‑op (modely neobsahují vazbu na vlastníka exportů).
