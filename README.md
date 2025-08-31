# CoachHub – Hockey Team Manager & Drill Board

Moderní webová aplikace ve Flasku pro správu hráčů, nominací, lajn a především tvorbu a přehrávání tréninkových cvičení s možností exportu do PDF, sdílení i komunitního „drill boardu“ mezi trenéry.

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

## 🏒 Nové rozšíření (Multi-team)
Pozn.: Tato část je plán/roadmapa, implementace probíhá.
- Registrace a login: username + heslo, každý trenér má svůj účet.
- Týmový profil: logo, primární a sekundární barva.
- Oddělená data per tým: hráči, cvičení, lajny i exporty jsou unikátní.
- Branding: UI aplikace se zobrazuje v barvách a s logem týmu.
- Sdílení cvičení mezi týmy: trenér může cvičení označit jako shared; ostatní týmy ho uvidí v komunitní knihovně (volitelné).

## ⚙️ Požadavky
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
python3 coach/app.py
```
Aplikace běží na http://127.0.0.1:5000/.
První spuštění vytvoří SQLite DB `coach/players.db`.

## 🗂 Navigace (horní menu)
- Domů
- Hráči
- Soupiska
- Lajny (nastavení, seznam sestav, export do PDF)
- Tréninky (nové cvičení, kategorie, export PDF, seznam uložených tréninků, shared drills)

## 📄 Exporty
- Cvičení: vybraná cvičení → PDF → uloží se do `static/exports/` (v multi-team režimu do `static/exports/<team_id>/`).
- Lajny: aktuální sestava → PDF → uloží se do `static/exports/` (v multi-team režimu do `static/exports/<team_id>/`).
- Sdílení přes WhatsApp / Web Share API.

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
