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

Autor: Martin Šnajdr – interní nástroj pro trenéry (HC Smíchov 1913 → univerzální použití).