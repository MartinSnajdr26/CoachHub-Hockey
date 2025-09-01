# CoachHub – Hockey Team Manager & Drill Board

Moderní webová aplikace ve Flasku pro správu hráčů, nominací, lajn a především tvorbu a přehrávání tréninkových cvičení s možností exportu do PDF, sdílení i komunitního „drill boardu“ mezi trenéry. Aplikace podporuje více týmů (multi‑team), potvrzení e‑mailu, reset hesla a chráněné exporty.

## 🎬 Quick demo (placeholders)
> Nahraď odkazy svými soubory v `docs/screenshots/`.

![Dashboard](docs/screenshots/dashboard_placeholder.png)
![Editor cvičení](docs/screenshots/editor_placeholder.png)
![Přehrávání cvičení (GIF)](docs/screenshots/demo_drill_placeholder.gif)
[▶ Video demo (MP4)](docs/screenshots/demo_drill_placeholder.mp4)

## 🚀 Přehled funkcí
- Hráči: evidence hráčů (F/D/G), úpravy, mazání.
- Nominace: výběr hráčů do zápasu (soupiska).
- Lajny: rozdělení nominovaných do útoků, obran a gólmanů.
- Cvičení (drills): editor na hřišti s animacemi, pohyby, ukládáním.
- Přehrávání cvičení: sekvenční i skupinový režim s chytrou synchronizací.
- Export PDF:
  - Cvičení → vícestránkové PDF (A4).
  - Lajny → sestava do zápasu s datem a soupeřem.
- Seznam exportů: přehled uložených tréninkových jednotek i sestav.
- Sdílení: WhatsApp odkaz nebo Web Share API (na mobilech).
- Automatické mazání starých exportů (pokud nejsou přiřazené).
- Kalendář událostí týmu (tréninky/zápasy) s 24h časem.
- Admin Audit log (schvalování členů, změny rolí, reset hesla, změny brandingu).

## 🏒 Multi‑team režim
- Registrace + přihlašování (hesla pásmovaná přes bcrypt).
- Týmy mají oddělená data (hráči, cvičení, lajny, kalendář, exporty).
- Branding (logo + barvy) na úrovni týmu, upload loga s validací a konverzí na PNG.
- Admin týmu schvaluje nové členy, nastavuje role (coach/player).

## ⚙️ Požadavky
- Python 3.10+
- Balíčky viz `requirements.txt`

## Instalace (dev)
```
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env   # vyplň podle potřeby (dev)
```

## Spuštění
```
python3 coach/app.py
```
Aplikace běží na http://127.0.0.1:5000/.

Databáze: v dev se vytvoří dle `DB_URL` (např. `sqlite:///data/dev.sqlite3`).

Alembic migrace (doporučeno pro existující DB):
```
FLASK_APP=coach/app.py flask db upgrade
```

E‑maily (ověření, reset hesla) – nastav SMTP v `.env`:
```
SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_SENDER
```

## 🗂 Navigace (horní menu)
- Domů
- Hráči
- Soupiska
- Lajny (nastavení, seznam sestav, export do PDF)
- Tréninky (nové cvičení, kategorie, export PDF, seznam uložených tréninků, shared drills)

## 📄 Exporty
- Exporty se ukládají do chráněné složky `coach/protected_exports/` (mimo `/static`).
- Stahování výhradně přes chráněnou trasu `/exports/<filename>` po přihlášení a ověření příslušnosti k týmu.
- Sdílení přes WhatsApp / Web Share API (odkazy jsou chráněné — příjemce musí mít přístup).

## 🖼️ Screenshots (placeholders)
> Nahraď tyto cesty vlastními obrázky v `docs/screenshots/`.

![Přehrávač cvičení – statický náhled](docs/screenshots/player_placeholder.png)
![Výběr exportu](docs/screenshots/export_select_placeholder.png)
![Seznam exportů](docs/screenshots/exports_list_placeholder.png)
![Lajny a export sestavy](docs/screenshots/lines_placeholder.png)

## 🛣 Roadmapa vývoje

| Fáze               | Funkce                                        | Stav | Cíl                               |
|--------------------|-----------------------------------------------|------|-----------------------------------|
| 1. Stabilní základ | Hráči, lajny, editor, exporty PDF            | ✅   | Interní nástroj pro 1 tým        |
| 2. Multi-team      | Login, registrace, logo+barvy, oddělená data | 🚧   | Každý tým má vlastní prostor     |
| 3. Sdílení cvičení | Knihovna sdílených drillů mezi týmy          | ⏳   | Komunita trenérů                  |
| 4. Extra funkce    | Statistiky, historie tréninků, časovač       | ⏳   | Vyšší přidaná hodnota            |
| 5. Future vision   | SaaS verze, více týmů, premium               | 🔮   | Další krok, pokud bude zájem     |

## 📌 Future vision
- Komunitní knihovna drillů mezi kluby, s možností vyhledávání a tagování.
- Více rolí v týmu (admin, trenér, asistent).
- Offline režim (PWA) a případná mobilní aplikace.
- Pokud se osvědčí, může vzniknout i cloudová / prémiová verze pro více klubů.

---

Autor: CoachHub Hockey – nástroj pro trenéry, hráče a kluby.
Logo: (placeholder)

---

## 🔐 Bezpečnost (shrnutí)
- CSRF ochrana (Flask‑WTF) pro všechny formuláře.
- Rate limiting (globální + přísnější na login/reset).
- Hesla hashovaná přes bcrypt.
- Verifikace e‑mailu přes časově omezený token (ItsDangerous).
- Reset hesla přes časově omezený token.
- RBAC: operace coach‑only; admin může schvalovat/odebírat členy a role.
- Oddělení dat per tým ve všech dotazech a zápisech.
- Chráněné exporty PDF (mimo `/static`, kontrola příslušnosti k týmu, ochrana proti path traversal).
- Bezpečné cookies (Secure/HttpOnly/SameSite) + HSTS v produkci.
- Security headers: CSP, X‑Frame‑Options, X‑Content‑Type‑Options, Referrer‑Policy, Permissions‑Policy.
- Audit log klíčových administrativních akcí.

Pozn.: V dev režimu je CSP tolerantnější kvůli inline skriptům; postupně přesouváme editor do externích JS souborů.
