# masfilipa-blog

Automatický generátor blog postov pre [masfilipa.sk](https://masfilipa.sk).

## Ako to funguje

1. GitHub Actions spúšťa skript každý **pondelok o 9:00**
2. Python skript zavolá **Claude API** a vygeneruje článok (350-450 slov, SK)
3. **Brevo** pošle email s náhľadom a dvoma tlačidlami
4. Klikneš **✅ Pridať na web** → článok sa automaticky uloží na server
5. Klikneš **❌ Zamietnuť** → nič sa nestane

## GitHub Secrets (nastaviť v Settings → Secrets → Actions)

| Secret | Popis |
|--------|-------|
| `ANTHROPIC_API_KEY` | API kľúč z console.anthropic.com |
| `BREVO_API_KEY` | API kľúč z Brevo |
| `APPROVE_SECRET` | Ľubovoľný tajný reťazec (napr. `masfilipa2025blog!`) |
| `AUTHOR_EMAIL` | Tvoj email kam prídu schvaľovacie emaily |

## Súbory na nahratie na Websupport (/web/)

- `approve_post.php` → `/web/approve_post.php`
- `web/blog/index.html` → `/web/blog/index.html`

## Manuálne spustenie

GitHub → Actions → Generate Blog Post → Run workflow
