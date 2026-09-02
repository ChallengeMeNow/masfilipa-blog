# masfilipa-blog — CLAUDE.md

## Repozitár
Automatický generátor blog článkov pre masfilipa.sk. Python skript v GitHub
Actions (cron pondelok 9:00) vygeneruje SK článok cez Claude API, pošle ho
mailom cez Brevo, a po kliknutí na "Pridať" PHP webhook na Websupporte
uloží HTML do /web/blog/.

Produkcia: https://masfilipa.sk/blog/
Repo: ChallengeMeNow/masfilipa-blog

## Adresárová štruktúra
```
.
├── generate_post.py                     # Python generátor (beží v GH Actions)
├── approve_post.php                     # PHP webhook → nasadený na Websupport /web/
├── index.html                           # Blog listing → nasadený na /web/blog/index.html
├── last_post.json                       # Posledný vygenerovaný článok (commitne ho bot)
├── canonical_fix.php                    # Jednorazovka, SPUSTENÁ 26. 8. 2026 — už nespúšťať
├── .github/workflows/generate_post.yml  # Cron + workflow_dispatch
└── README.md
```

## Dátová štruktúra

`last_post.json` (v repe, prepisuje sa každý pondelok):
```json
{
  "slug": "url-friendly-slug",
  "title": "Titulok článku",
  "date": "18. 5. 2026",
  "ebook": "Názov súvisiaceho e-booku",
  "topic_index": 3,
  "variant_index": 1,
  "html": "<!DOCTYPE html>...celý HTML súbor článku..."
}
```
`topic_index` + `variant_index` slúžia na regeneráciu po feedbacku — vrátia
presne tú istú tému aj variant. Články spred 26. 8. 2026 `variant_index`
nemajú, vtedy sa berie variant 0.

`posts.json` (na Websupporte v `/web/blog/posts.json`) — pole článkov, ktoré číta `index.html`:
```json
[{ "slug": "...", "title": "...", "date": "...", "ebook": "..." }, ...]
```

## Témy
16 tém v `TOPICS` v `generate_post.py`, každá s 3 long-tail variantmi.
Téma má spoločné: `keywords`, `ebook`, `ebook_url`.
Variant má vlastné: `title_hint`, `primary_keyword`, `angle`.

Rotácia (`get_topic_indexes_for_week`) počíta týždne od `WEEK_EPOCH`
(13. 4. 2026), nie z čísla ISO týždňa — to sa na prelome roka resetuje a
zopakovalo by tému po štyroch týždňoch. Téma sa mení každý týždeň, variant
až po prejdení celého kola → rovnaké `primary_keyword` sa vráti raz za 48
týždňov.

Keywordy sú zámerne long-tail. Head termy („manažment tímu") skončili na
pozíciách 27–45 a články si o ne navzájom konkurovali.

## Secrets (GitHub → Settings → Secrets → Actions)
- `ANTHROPIC_API_KEY` — Claude API
- `BREVO_API_KEY` — Brevo transactional email
- `APPROVE_SECRET` — HMAC kľúč pre approve tokeny (musí byť rovnaký
  v `approve_post.php` — TODO: presunúť aj v PHP do env)
- `AUTHOR_EMAIL` — kam chodia schvaľovacie emaily

## Pravidlá
- Komunikácia po slovensky.
- Git: commit, push, pull aj merge robím sám a bez pýtania sa — podľa
  globálneho `~/.claude/CLAUDE.md`. Deštruktívne operácie (`push --force`,
  `reset --hard`, mazanie branchov) len so súhlasom.
  (Do 2. 9. 2026 tu stálo „NIKDY nerobiť `git push`" + „commity len so
  súhlasom" — zastarané, Filip to pravidlo zrušil.)
- Nepridávať testy / build systémy / abstrakcie bez požiadavky — je to
  zámerne low-tech projekt.
- `last_post.json` prepisuje bot každý pondelok — neukladať tam ručne
  nič dôležité.
- Zmeny v `approve_post.php` a `index.html` sa musia ručne nahrať na
  Websupport (FTP / file manager) — repo ich nedeployuje.

## Pending
- Search Console: *Request indexing* na dva články, ktoré Google crawloval
  a neindexoval — `time-management-manazer-system-zarabaj-vs-buduj`
  (crawl 26. 8.) a `manazment-timu-5-chyb-ktore-robia-aj-skuseni-manazeri`
  (crawl 12. 8.). Ak ostanú vonku aj po requeste, nejde o rýchlosť crawlu,
  ale o duplicitu voči indexovaným súrodencom — vtedy témy zlúčiť.
- Zmazať z `/web/blog/` tri verejne dostupné zálohy po `canonical_fix.php`
  (`*.html.bak`) — vracajú HTTP 200 ako text/html. Canonical v nich sedí,
  takže o duplicitu nejde, je to poriadok.
- Zvážiť update modelu z `claude-opus-4-5` na `claude-opus-4-7`
  (alebo `claude-sonnet-4-6` pre úsporu).

## Stav SEO (2. 9. 2026)
Baseline 8. 6. 2026: 10 impresií/28 dní, 0 klikov, 3 indexované stránky.
Stav 2. 9. 2026: 24 impresií/28 dní, 0 klikov, **19 z 22 URL indexovaných**.
Kanonizácia z augusta zabrala. Rast impresií sa ale zastavil — 9 impresií
za posledné dva týždne po sebe, bez zmeny.

Hotové, nevracať sa k tomu:
- `<title>` + meta description homepage prepísané.
- Meta description článku o prokrastinácii prepísaná na click-driven
  znenie (nahrané 2. 9. 2026). Titulok ostal — stránka je na pozícii 5,2
  a 6 impresií nie je dôvod ním hýbať.
- Kanonizácia blogu — canonical sedí na všetkých kontrolovaných článkoch.
- Anchor linky (`#ebooks`, `#about`, `#reviews`) sú zo sitemapy preč.
