# CoachHub Hockey  
⚡ Open-source webová aplikace pro trenéry a hráče hokeje.  
📋 Správa hráčů, sestav, tréninků a exportů do PDF – vše na jednom místě.  
*(Původně vyvinuto pro HC Smíchov 1913, nyní univerzálně použitelné.)*  

👉 **Cíl:** zjednodušit organizaci týmu, ušetřit čas trenérům a zpřehlednit práci s tréninky a sestavami.  
👉 **Technologie:** Python (Flask), SQLite/Postgres/MySQL, HTML/CSS/JS.  

---

## ✨ Funkce
- **Hráči** – evidence, úpravy, mazání (F/D/G).  
- **Soupiska** – nominace hráčů do zápasu.  
- **Lajny** – rozdělení nominovaných do 4 útoků + 4 obran a 2 brankářů.  
- **Cvičení (drills)** – editor na hřišti s ikonami, animacemi a skupinami pohybů.  
- **Přehrávání cvičení** – sekvenční i skupinový režim se synchronizací.  
- **Export do PDF**  
  - vybraná cvičení (vícestránkové PDF, A4),  
  - lajny (jednostránkové PDF „Sestava – Zápas – soupeř – datum“).  
- **Seznam exportů** – přehled tréninků i sestav, možnost stáhnout/otevřít/sdílet/smazat.  
- **Sdílení přes WhatsApp / Web Share API** (funguje i na mobilech).  
- **Automatické čištění exportů** – nepoužívané PDF starší než 14 dní se smažou.  

---

## ⚙️ Požadavky
- Python **3.10+**  
- Knihovny viz `requirements.txt`  

---

## 🚀 Instalace & spuštění

```bash
# virtuální prostředí
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# instalace balíčků
pip install -r requirements.txt

# spuštění aplikace
python3 -m coach.app

Alternativně přes Flask CLI:

export FLASK_APP=coach.app:app && flask run


Aplikace běží na http://127.0.0.1:5000
.
První spuštění v dev vytvoří SQLite DB automaticky.

🛠 Konfigurace (.env)

Založ .env podle .env.example a nastav:

SECRET_KEY – náhodný klíč (v produkci povinné).

APP_ENV – dev nebo production.

DB_URL – např. sqlite:///coach/dev.db nebo plná URL (Postgres/MySQL).

TERMS_VERSION – verze Podmínek (např. v1.0).

.env je ignorován v Git – nikdy necommituješ tajné údaje.

🗂 Navigace

Domů, Hráči, Soupiska, Lajny

Tréninky

Nové cvičení

Kategorie

Export cvičení do PDF

Seznam tréninků

Lajny

Nastavit lajny

Export sestavy

📄 Exporty

Cvičení → PDF uložené v coach/protected_exports/, dostupné v seznamu tréninků.

Lajny → PDF se jménem soupeře a datem, uložené stejně.

Sdílení funguje přes odkaz (WhatsApp) nebo Web Share API.

💾 Databáze

Default: coach/players.db (SQLite).

Tabulky:

player, roster, line_assignment, drill

training_session (exporty cvičení)

lineup_session (exporty lajn)

V dev se schema vytvoří přes db.create_all().
V produkci používej migrace (Alembic).

🔐 Přihlášení & týmy

Registrace = vytvoření týmu (název, barvy, logo).

Přístup pouze přes týmové klíče (coach / player).

Rotace klíčů možná v administraci.

Při změně TERMS_VERSION se vyžaduje nový souhlas.

📑 Právní & privacy

/terms – Podmínky použití (verze z .env).

/privacy – Zásady ochrany osobních údajů.

Kontakt: martinsnajdr@coachhubhockey.com

🔧 Vývoj

Změny závislostí → aktualizuj requirements.txt.

Font pro PDF: arial.ttf (fallback na default Pillow).

Výstup PDF: A4, 72 DPI (595×842 px).

Chování WhatsApp/Share API se liší podle prohlížeče.

📦 Produkční tipy

Nastav silný SECRET_KEY v .env.

HTTPS (HSTS + secure cookies se zapnou v produkci automaticky).

Gunicorn + nginx doporučeno.

Používej migrace (flask db upgrade).

---

🔐 Obnova trenérského klíče (CLI, bezpečně)

Pokud trenér ztratí klíč, nejbezpečnější je rotace klíče přes konzoli (bez veřejných endpointů). Plaintext nového klíče se ukáže jen jednou v konzoli – nikde se neukládá.

Postup (PythonAnywhere/SSH)

1) Otevři Bash konzoli a aktivuj venv

   - `source ~/.venvs/coachhub/bin/activate`

2) Nastav Flask app

   - `export FLASK_APP=coach.app:app`

3) Spusť `flask shell`

4) V shelli vlož a uprav snippet (změň `TEAM` a případně `ROLE`)

```
from coach.extensions import db
from coach.models import Team, TeamKey, AuditEvent
from coach.services.keys import gen_plain_key, hash_team_key
from datetime import datetime

# Nastavení: název týmu (nebo ID) a role
TEAM = "HC Smíchov 1913"   # nebo např. 42 pro ID
ROLE = "coach"              # "coach" | "player"

# Najdi tým podle názvu/ID
team = Team.query.filter(Team.name==TEAM).first() if isinstance(TEAM, str) else Team.query.get(int(TEAM))
assert team, "Team not found"

now = datetime.utcnow()
# Deaktivuj stávající aktivní klíče dané role
TeamKey.query.filter_by(team_id=team.id, role=ROLE, active=True).update({TeamKey.active: False, TeamKey.rotated_at: now})

# Vygeneruj nový klíč a ulož hash
plain = gen_plain_key()
db.session.add(TeamKey(team_id=team.id, role=ROLE, key_hash=hash_team_key(plain), active=True))

# Audit (IP zkrácena na symbolický údaj "admin")
try:
    db.session.add(AuditEvent(event='team.key_rotated', team_id=team.id, role='coach', ip_truncated='admin', meta=f'{{"role":"{ROLE}"}}'))
except Exception:
    pass

db.session.commit()
print("NEW_KEY=", plain)
```

5) Bezpečně předej nový klíč trenérovi (mimo aplikaci). Klíč nikam neloguj ani nevkládej do URL.

Poznámky

- Rotace je okamžitá – starý klíč přestane fungovat hned.
- Pro roli hráče změň `ROLE = "player"`.
- V produkci vždy přes HTTPS/SSH.

Placená varianta (návrh)

- Klíče mohou být platné 30 dní (kontrola při přihlášení) a obnova povolena až po zaplacení.
- Doporučeno zobrazovat v Nastavení počet dnů do expirace a všechny rotace logovat do audit logu.

Autor: Martin Šnajdr – interní nástroj pro trenéry (HC Smíchov 1913 → univerzální použití).
