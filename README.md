# CoachHub Hockey  
Open-source webová aplikace pro správu hokejového týmu – hráči, lajny, tréninky a exporty do PDF.  
*(Původně vyvinuto pro HC Smíchov 1913, nyní univerzální použití.)*


## Přehled funkcí
- Hráči: evidence hráčů (F/D/G), úpravy, mazání.
- Nominace: výběr hráčů do zápasu (soupiska).
- Lajny: rozdělení nominovaných do 4 útoků + 4 obraných dvojic a 2 brankáře.
- Cvičení (drills): editor na hřišti s animacemi, skupinami pohybů a ukládáním.
- Přehrávání cvičení: chytré párování ikon a pohybů, sekvenční i skupinový režim.
- Export PDF:
  - Vybraná cvičení → vícestránkové PDF (A4).
  - Aktuální lajny → jednostránkové PDF „Sestava – Zápas – ‚soupeř‘ – datum“.
- Seznam uložených exportů: přehled „Tréninkové jednotky“ i „Sestavy“, stahování/otevření/sdílení/mazání.
- Sdílení přes WhatsApp: přes odkaz, případně přes Web Share API (na mobilech sdílení souboru).

## Požadavky
- Python 3.10+
- Balíčky viz `requirements.txt`

## Instalace
```
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Spuštění
```
python3 -m coach.app
```
Případně přes Flask CLI: `export FLASK_APP=coach.app:app && flask run`.
Apka běží na http://127.0.0.1:5000/.
První spuštění v dev automaticky vytvoří SQLite DB (viz `DB_URL` níže),
jinak fallback na `coach/players.db`.

## Konfigurace (.env)
- Doporučeno: `cp .env.example .env` a upravit hodnoty podle potřeby.
- Klíčové proměnné:
  - `SECRET_KEY`: náhodný tajný klíč (nutné pro produkci).
  - `APP_ENV`: `dev`/`production` (v dev se uvolní secure cookies a povolí debug).
  - `DB_URL`: např. `sqlite:///coach/dev.db` nebo plná URL (Postgres/MySQL). Relativní cesta
    k SQLite se automaticky převede na absolutní a adresář se vytvoří.
  - `TERMS_VERSION`: verze Podmínek pro správu souhlasů (např. `v1.0`).

Poznámka: Tato verze nepoužívá e‑maily (SMTP) ani e‑mailové ověření; přihlášení je výhradně přes týmové klíče. `.env` je ignorován ve `.gitignore` – nikdy necommituje tajné údaje.

## Navigace (horní menu)
- Domů, Hráči, Soupiska, Lajny.
- Tréninky (dropdown):
  - ➕ Nové cvičení
  - 📂 Kategorie (přehled kategorií cvičení)
  - 📄 Export vybraná cvičení (výběr drillů a export do PDF)
  - 🗂 Seznam tréninků (uložené exporty tréninkových jednotek)
- Lajny (dropdown):
  - ⚙️ Nastavit lajny
  - 🗂 Seznam sestav

## Cvičení (editor)
- Nástroje pohybu: bez puku, s pukem, volný, jízda vzad, nahrávka, střela atd.
- Ikony hráčů: F (modré kolečko), D (červený trojúhelník), G (černé kolečko).
- Synchronizace hráčů: „Začít synchronizaci“/„Ukončit synchronizaci“ – pohyby uvnitř skupiny startují současně.
- „Sync po přihrávce (2 pohyby)“: po nahrávce spustí další 2 hráčské pohyby současně.
- Log sekvencí: přehled sekvencí/skupin dole pod plochou.

Ukládá se snímek (PNG Base64) i popis pohybů (JSON) – používá se při přehrávání i exportu.

## Export cvičení do PDF
- Tréninky → „📄 Export vybraná cvičení“.
- Vyhledej/zaškrtni cvičení, doplň název exportu (předvyplněno „Tréninková jednotka YYYY‑MM‑DD“).
- Tlačítko „📄 Vytvořit PDF“ uloží PDF do `coach/protected_exports/` a přidá záznam do „Seznam tréninků“.
- Výsledková stránka: stáhnout/otevřít/sdílet (WhatsApp/Share API).

## Export lajn do PDF
- Lajny → dole „Export sestavy do PDF“.
- Vyplň „Soupeř“ a „Datum“. Název se složí jako: `Sestava - Zápas - "soupeř" - datum`.
- PDF se uloží do `coach/protected_exports/` a vytvoří se záznam v „Seznam sestav“.

## Sdílení přes WhatsApp
- Webový WhatsApp umí poslat text (odkaz). Tlačítko „📲 Sdílet odkaz“ otevře chat s předvyplněným odkazem na PDF.
- Tlačítko „📎 Sdílet soubor“ využívá Web Share API (funguje hlavně na mobilních prohlížečích a s HTTPS). Pokud není dostupné, spadne na sdílení odkazu.
- Pro reálné sdílení mimo lokální síť je potřeba veřejná URL (např. nasazení na serveru nebo tunel typu ngrok).

## Automatické mazání exportů
- Funkce `cleanup_exports()` maže v `coach/protected_exports/` pouze „osamocené“ PDF (nepřiřazené k žádnému uloženému exportu) starší než 14 dní.
- PDF přiřazená k uloženým „Tréninkovým jednotkám“ nebo „Sestavám“ se nemažou.

## Databáze
- SQLite soubor: `coach/players.db`.
- Tabulky:
  - `player`, `roster`, `line_assignment`, `drill`.
  - `training_session` – uložené exporty vybraných cvičení.
  - `lineup_session` – uložené exporty sestav lajn.
- DB se vytváří při spuštění (`db.create_all()`).

## Vývoj a poznámky
- Po změně závislostí aktualizuj `requirements.txt`.
- Fonty v PDF: používá se systémový `arial.ttf`, jinak fallback na default font Pillow.
- PDF rozlišení: A4 @ 72 DPI (595×842 px). Obrázky cvičení se škálují s poměrem stran.
- WhatsApp/Share API chování se může lišit podle prohlížeče/zařízení.

## Provozní poznámky (production)
- `SECRET_KEY`: nastav v `.env` silnou hodnotu (bezpečné cookies, podepisování tokenů).
- Přihlášení: používají se pouze týmové klíče (bez e‑mailů/SMTP).
- HTTPS: v produkci se automaticky zapne HSTS a secure cookies (`SESSION_COOKIE_SECURE=1`).
- Migrace DB: používej Alembic migrace (`migrations/`). Pro lokální dev je k dispozici fallback `db.create_all()`.

---

Autor: Martin Snajdr – interní nástroj pro trenéry.

## Aktualizovaný návod (2025)

### Rychlý start (dev)
- Virtuální prostředí + instalace:
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
- `.env` v kořeni repa:
  - `APP_ENV=dev`
  - `SECRET_KEY=dev-secret-change-me`
  - `TERMS_VERSION=v1.0`
- Spuštění:
  - `python3 -m coach.app`
  - nebo `export FLASK_APP=coach.app:app && flask run`

### Migrace DB (Alembic)
- Poprvé: `FLASK_APP=coach.app:app flask db upgrade`
- Pokud DB existuje bez historie migrací: `flask db stamp head && flask db upgrade`

### Exporty a soubory
- PDF exporty jsou v chráněné složce `coach/protected_exports/` a servírují se přes `/exports/<filename>` s kontrolou oprávnění.
- Loga týmů se ukládají do `coach/static/uploads/` (PNG/JPG, max 2 MB), s deduplikací obsahem.

### Přihlášení (týmové klíče) a souhlasy
- Přihlašování probíhá bez e‑mailů/hesel – pouze týmovým klíčem.
- `/team/auth`: taby „Přihlášení / Vytvořit tým“.
- Vytvořit tým: zadej název, barvy a případně logo; systém vygeneruje 2 klíče – pro roli `coach` a `player` (zobrazeny jen jednou).
- Přihlášení: vyber tým, roli (`coach`/`player`) a vlož odpovídající klíč.
- Rotace klíčů: trenér na `/team/keys` může vygenerovat nové klíče (staré se deaktivují).
- Souhlasy: akceptace Podmínek je povinná; při změně `TERMS_VERSION` se může vyžadovat opětovný souhlas (`/terms/consent`).

### Právní a privacy
- Podmínky použití: `/terms` (hlavička zobrazuje `TERMS_VERSION`).
- Zásady ochrany osobních údajů: `/privacy`.
- Kontakt pro žádosti: `martinsnajdr@coachhubhockey.com`.

### Audit log a administrace
- `/admin/audit-log` (pouze týmoví administrátoři) – akce se členy týmu, změny brandu, správa klíčů, souhlasy apod.

### Retence uživatelů
- Služba: `coach/services/retention.py` → `prune_inactive_users(days)` smaže neaktivní účty (mimo adminů).
- CLI: `FLASK_APP=coach.app:app flask retention:prune --days 365`
- Více: `docs/retention.md` (cron příklad).

### Produkční provoz – tipy
- Gunicorn + reverse proxy (nginx) a skutečný `SECRET_KEY`.
- Flask‑Limiter: nastavte perzistentní storage (např. Redis), defaultní in‑memory není pro produkci.
- Bezpečnost: CSP s nonce, HSTS a secure cookies v produkci.
