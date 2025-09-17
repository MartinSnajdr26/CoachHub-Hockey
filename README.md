# CoachHub Hockey
Open‑source webová aplikace pro trenéry a hráče hokeje. Správa hráčů, soupisky, formací, tréninků a exportů do PDF – vše na jednom místě.

- Cíl: zjednodušit organizaci týmu a ušetřit čas trenérům.
- Technologie: Python (Flask), SQLite/Postgres/MySQL, HTML/CSS/JS.

---

## Funkce
- Hráči: evidence, úpravy, mazání (F/D/G).
- Soupiska: výběr nominovaných hráčů pro zápas.
- Formace (Lajny): drag&drop i „tap‑to‑assign“, 4 útoky, 4 obrany, 2 G; barvy karty na míru, per‑karta uložení; mobilní „swiper“ mezi kartami.
- Tréninky (Drills): kreslení na hřiště, skupiny pohybů, přehrávání animací, export do PDF.
- Kalendář: měsíční přehled tréninků a zápasů, rychlé přidání/úprava (mobilní toast/sheet, desktop overlay), sdílení detailu.
- Exporty do PDF: vybraná cvičení (vícestránkové A4) a sestavy lajn (jednostránkové); sdílení přes Web Share API/WhatsApp.
- Seznam exportů: přehled, stažení/otevření/sdílení/smazání; automatické čištění starších PDF (14 dní).
- Nastavení týmu: název, barvy (primární/sekundární), logo; nástroje pro klíče týmu.
- Audit log: základní záznamy o akcích (přihlášení, rotace klíčů apod.).

Pozn.: Aplikace běží v „team‑only“ režimu – žádní uživatelé/hesla, přístup je přes týmové klíče pro role coach/player.

---

## Požadavky
- Python 3.10+
- `pip install -r requirements.txt`

---

## Instalace a spuštění
```
# Vytvoření a aktivace venv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Instalace závislostí
pip install -r requirements.txt

# Spuštění
python3 -m coach.app
# nebo
export FLASK_APP=coach.app:app && flask run
```
- Aplikace poběží na `http://127.0.0.1:5000`.
- Při prvním spuštění se v dev vytvoří SQLite databáze automaticky.

### Konfigurace (.env)
Vytvoř `.env` podle `.env.example`:
- `SECRET_KEY`: náhodný tajný klíč (v produkci povinné).
- `APP_ENV`: `dev` nebo `production`.
- `DB_URL`: např. `sqlite:///coach/dev.db` nebo plná URL na Postgres/MySQL.
- `TERMS_VERSION`: verze Podmínek (např. `v1.0`).
- `SESSION_LIFETIME_DAYS`: platnost týmové session (default 30).

---

## Navigace v aplikaci
- Domů: dashboard, kalendář, nástěnka zpráv.
- Hráči, Soupiska, Formace (Sestavit, Seznam sestav).
- Tréninky (Nové cvičení, Kategorie, Výběr a export, Seznam tréninků).
- Nastavení, Audit log (pro coach).

---

## Exporty
- Uložené PDF jsou v `coach/protected_exports/` (mimo `/static`).
- Sdílení: WhatsApp / Web Share API.
- Retence: starší PDF (14 dní) se automaticky mažou.

---

## Databáze a migrace
- Default SQLite: `coach/players.db` (lze změnit přes `DB_URL`).
- Hlavní tabulky: `player`, `roster`, `line_assignment`, `drill`, `training_session`, `lineup_session`, `team`, `team_key`, `audit_event`, `training_event`, `team_login_attempt`.
- Produkce: používej migrace (Alembic) – `flask db upgrade`.

---

## Přihlášení a klíče týmu
- Přihlášení probíhá přes týmové klíče: role `coach` / `player`.
- Vytvoření týmu (název, barvy, logo) vygeneruje oba klíče; zobrazí se jen jednou.

### Rotace/obnova klíčů (doporučeno v UI)
- Jako trenér otevři stránku Klíče týmu (`/team/keys` nebo přes Nastavení) a zvol „Vygenerovat nový klíč“ pro `coach` nebo `player`.
- Nový klíč se zobrazí jednorázově – bezpečně ho ulož a sdílej mimo aplikaci.

### Rotace/obnova klíčů (CLI varianta)
Bezpečná alternativa přes konzoli/SSH. Plaintext nového klíče se ukáže pouze v terminálu a neukládá se.

1) Aktivuj venv a nastav Flask app:
```
source .venv/bin/activate
export FLASK_APP=coach.app:app
flask shell
```
2) V shelli spusť (uprav `TEAM` dle názvu/ID a `ROLE`):
```
from coach.extensions import db
from coach.models import Team, TeamKey, AuditEvent
from coach.services.keys import gen_plain_key, hash_team_key
from datetime import datetime

TEAM = "HC Smíchov 1913"  # nebo např. 42 pro ID
ROLE = "coach"            # "coach" | "player"

team = Team.query.filter(Team.name==TEAM).first() if isinstance(TEAM, str) else Team.query.get(int(TEAM))
assert team, "Team not found"

now = datetime.utcnow()
TeamKey.query.filter_by(team_id=team.id, role=ROLE, active=True).update({TeamKey.active: False, TeamKey.rotated_at: now})

plain = gen_plain_key()
db.session.add(TeamKey(team_id=team.id, role=ROLE, key_hash=hash_team_key(plain), active=True))
try:
    db.session.add(AuditEvent(event='team.key_rotated', team_id=team.id, role='coach', ip_truncated='admin', meta=f'{{"role":"{ROLE}"}}'))
except Exception:
    pass
db.session.commit()
print("NEW_KEY=", plain)
```
3) Předat trenérovi mimo aplikaci. Starý klíč přestává platit okamžitě.

---

## Poznámky k UI/UX
- Barvy značky: `--brand-primary` (pozadí), `--brand-secondary` (text na tmavém podkladu). Aplikace dopočítá `--on-primary`/`--on-secondary` pro čitelnost i při špatném zvolení barev.
- Formace: barvy jednotlivých karet se ukládají per karta (localStorage) a kontroluje se kontrast textu.
- Mobil: hamburger menu, swiper mezi formacemi, toast/sheet interakce v kalendáři.

---

Autor: Martin Šnajdr  
Kontakt: martinsnajdr@coachhubhockey.com

