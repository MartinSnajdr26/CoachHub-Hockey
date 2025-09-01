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
python3 coach/app.py
```
Aplikace běží na http://127.0.0.1:5000/.
První spuštění automaticky vytvoří SQLite DB `coach/players.db`.

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
- Tlačítko „📄 Vytvořit PDF“ uloží PDF do `coach/static/exports/` a přidá záznam do „Seznam tréninků“.
- Výsledková stránka: stáhnout/otevřít/sdílet (WhatsApp/Share API).

## Export lajn do PDF
- Lajny → dole „Export sestavy do PDF“.
- Vyplň „Soupeř“ a „Datum“. Název se složí jako: `Sestava - Zápas - "soupeř" - datum`.
- PDF se uloží do `coach/static/exports/` a vytvoří se záznam v „Seznam sestav“.

## Sdílení přes WhatsApp
- Webový WhatsApp umí poslat text (odkaz). Tlačítko „📲 Sdílet odkaz“ otevře chat s předvyplněným odkazem na PDF.
- Tlačítko „📎 Sdílet soubor“ využívá Web Share API (funguje hlavně na mobilních prohlížečích a s HTTPS). Pokud není dostupné, spadne na sdílení odkazu.
- Pro reálné sdílení mimo lokální síť je potřeba veřejná URL (např. nasazení na serveru nebo tunel typu ngrok).

## Automatické mazání exportů
- Funkce `cleanup_exports()` maže v `coach/static/exports/` pouze „osamocené“ PDF (nepřiřazené k žádnému uloženému exportu) starší než 14 dní.
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

---

Autor: HC SMÍCHOV 1913 – interní nástroj pro trenéry.

