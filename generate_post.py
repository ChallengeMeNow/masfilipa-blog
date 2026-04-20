#!/usr/bin/env python3
"""
masfilipa.sk — Automatický generátor blog postov
Každý pondelok vygeneruje článok a pošle ho na schválenie.
"""

import os
import json
import hashlib
import hmac
import random
import re
import requests
from datetime import datetime
import anthropic

# --- KONFIGURÁCIA ---
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
BREVO_API_KEY     = os.environ['BREVO_API_KEY']
APPROVE_SECRET    = os.environ['APPROVE_SECRET']
AUTHOR_EMAIL      = os.environ['AUTHOR_EMAIL']
BASE_URL          = 'https://masfilipa.sk'
APPROVE_ENDPOINT  = f'{BASE_URL}/approve_post.php'

# --- TÉMY ČLÁNKOV ---
# Rotujú automaticky, každý týždeň iná téma
TOPICS = [
    {
        "title_hint": "Kariérny postup: kedy čakať a kedy odísť",
        "primary_keyword": "kariérny postup Slovensko",
        "keywords": "kariérny postup, zmena práce, kariéra, pracovný rast",
        "ebook": "Z kuchyne do riaditeľského kresla",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/20137683-17e6-409f-9855-5837402f7408",
        "angle": "Osobný príbeh čakania na postup. Konkrétne signály kedy má zmysel čakať a kedy je čas odísť. Kariérny postup nie je automatický — treba ho aktívne riadiť.",
    },
    {
        "title_hint": "Kedy vyhodiť zamestnanca — a prečo to odkladáme príliš dlho",
        "primary_keyword": "kedy vyhodiť zamestnanca",
        "keywords": "vyhadzovanie zamestnanca, manažment tímu, HR rozhodnutia, slabý výkon",
        "ebook": "Krava na Mount Evereste",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/86eb1eb1-8f5a-4dbc-b293-fcc359fe6596",
        "angle": "Prečo odkladáme ťažké rozhodnutia o ľuďoch a čo to stojí firmu. Metóda 3 sedení — kde už pri prvom je takmer jasné ako sa to bude vyvíjať. Detaily v ebooku.",
    },
    {
        "title_hint": "Time management pre manažérov — prečo nestíhate aj keď pracujete 10 hodín",
        "primary_keyword": "time management manažér",
        "keywords": "time management, manažment času, produktivita, priority",
        "ebook": "Zarábaj alebo buduj",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/d6153a14-0083-4e88-aa6e-181964b13fe8",
        "angle": "Systém zarábaj vs buduj. Prečo nie je problém čas ale priority. Ako rozoznať čo je dôležité od toho čo je len naliehavé.",
    },
    {
        "title_hint": "Ako sa rozhodnúť keď je každá možnosť zlá",
        "primary_keyword": "ako sa rozhodnúť v práci",
        "keywords": "rozhodovanie, ťažké rozhodnutia, kariéra, životné rozhodnutia",
        "ebook": "Ako sa rozhodnúť, keď sa zdá byť každé rozhodnutie zlé",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/6d78e957-ee7c-4378-b620-252a4c20bf1e",
        "angle": "Praktický systém rozhodovania z vlastnej skúsenosti. Prečo paralýza rozhodnutím je horšia ako zlé rozhodnutie. Konkrétne otázky ktoré pomáhajú.",
    },
    {
        "title_hint": "Ako motivovať zamestnancov — čo funguje a čo je len ilúzia",
        "primary_keyword": "ako motivovať zamestnancov",
        "keywords": "motivácia zamestnancov, manažment tímu, firemná kultúra, leadership",
        "ebook": "Krava na Mount Evereste",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/86eb1eb1-8f5a-4dbc-b293-fcc359fe6596",
        "angle": "Rozdiel medzi vonkajšou a vnútornou motiváciou v praxi. Čo manažéri robia zle. Malé veci ktoré fungujú lepšie ako bonusy.",
    },
    {
        "title_hint": "Zmena práce po 30 — strach alebo príležitosť",
        "primary_keyword": "zmena práce Slovensko",
        "keywords": "zmena práce, kariéra po tridsiatke, pracovná zmena, nová práca",
        "ebook": "Z kuchyne do riaditeľského kresla",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/20137683-17e6-409f-9855-5837402f7408",
        "angle": "Osobný príbeh zmeny. Prečo strach zo zmeny je normálny ale nesmie rozhodovať. Praktické kroky ako vyhodnotiť či zmena dáva zmysel.",
    },
    {
        "title_hint": "Prokrastinácia v práci — prečo odkladáme dôležité veci",
        "primary_keyword": "prokrastinácia v práci",
        "keywords": "prokrastinácia, odkladanie, produktivita, time management",
        "ebook": "Zarábaj alebo buduj",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/d6153a14-0083-4e88-aa6e-181964b13fe8",
        "angle": "Prokrastinácia nie je lenivosť — je to symptóm. Konkrétne techniky z praxe. Prečo systém funguje lepšie ako vôľa.",
    },
    {
        "title_hint": "Manažment tímu — 5 chýb ktoré robia aj skúsení manažéri",
        "primary_keyword": "manažment tímu",
        "keywords": "manažment tímu, riadenie ľudí, leadership, chyby manažéra",
        "ebook": "Krava na Mount Evereste",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/86eb1eb1-8f5a-4dbc-b293-fcc359fe6596",
        "angle": "Konkrétne chyby z vlastnej kariéry. Čo by som robil inak. Prečo dobré úmysly nestačia bez systému.",
    },
]

def get_topic_for_week():
    """Vyberie tému podľa čísla týždňa — rotuje automaticky."""
    week_num = datetime.now().isocalendar()[1]
    return TOPICS[week_num % len(TOPICS)]

def slugify(text):
    """Vytvorí URL-friendly slug zo slovenského textu."""
    replacements = {
        'á': 'a', 'ä': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'í': 'i',
        'ľ': 'l', 'ĺ': 'l', 'ň': 'n', 'ó': 'o', 'ô': 'o', 'ŕ': 'r',
        'š': 's', 'ť': 't', 'ú': 'u', 'ý': 'y', 'ž': 'z',
    }
    text = text.lower()
    for sk, en in replacements.items():
        text = text.replace(sk, en)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text[:60]

def generate_article(topic):
    """Zavolá Claude API a vygeneruje článok."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Si Filip — technický riaditeľ, konzultant a autor e-bookov na masfilipa.sk.
Píšeš po slovensky, priamym osobným štýlom. Žiadna teória, len skúsenosti z praxe.

Napíš blog post na tému: "{topic['title_hint']}"
Uhol pohľadu: {topic['angle']}
Primárne kľúčové slovo (MUSÍ byť v titulku a prvom odstavci): {topic['primary_keyword']}
Sekundárne kľúčové slová (použi prirodzene v texte 2-3x): {topic['keywords']}

POŽIADAVKY:
- Dĺžka: 400-500 slov
- Jazyk: slovenčina, hovorový ale profesionálny štýl
- Štruktúra: krátky úvod (1 odstavec, obsahuje primárne kľúčové slovo) → hlavný obsah (3-4 odstavce) → záver
- Použi 2-3 medzititulky (H2) — jeden H2 musí obsahovať primárne kľúčové slovo alebo jeho variáciu
- Osobné príbehy a konkrétne príklady, žiadne frázy
- Dávaj pozor na správnu slovenčinu: napr. "štyri mesiace" nie "štyroch mesiacov" v nominatíve
- Na konci NIČ o e-booku — to doplníme automaticky
- Vráť VÝHRADNE JSON v tomto formáte, bez markdown, bez backticks:

{{
  "title": "Titulok článku (max 60 znakov)",
  "meta_description": "Popis pre Google (max 155 znakov, obsahuje kľúčové slovo)",
  "content_html": "HTML obsah článku s <h2>, <p> tagmi. BEZ html/body/head tagov."
}}"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # Odstráni prípadné markdown backticks
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)

def build_full_html(article, topic, slug, date_str):
    """Zostaví kompletný HTML súbor pre blog post."""
    return f"""<!DOCTYPE html>
<html lang="sk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{article['title']} — Máš Filipa?</title>
  <meta name="description" content="{article['meta_description']}">
  <meta name="author" content="Filip Sidor">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{BASE_URL}/blog/{slug}.html">
  <meta property="og:title" content="{article['title']}">
  <meta property="og:description" content="{article['meta_description']}">
  <meta property="og:url" content="{BASE_URL}/blog/{slug}.html">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Máš Filipa?">
  <meta property="article:author" content="Filip Sidor">
  <meta property="article:published_time" content="{datetime.now().strftime('%Y-%m-%d')}">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": "{article['title']}",
    "description": "{article['meta_description']}",
    "author": {{
      "@type": "Person",
      "name": "Filip Sidor",
      "url": "{BASE_URL}"
    }},
    "publisher": {{
      "@type": "Organization",
      "name": "Máš Filipa?",
      "url": "{BASE_URL}"
    }},
    "datePublished": "{datetime.now().strftime('%Y-%m-%d')}",
    "url": "{BASE_URL}/blog/{slug}.html",
    "inLanguage": "sk"
  }}
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&family=Inter:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --teal: #0B3C49;
      --gold: #D4AF37;
      --text: #1a1a2e;
      --text-light: #5a5a72;
      --border: #dde6ea;
      --off-white: #F8FAFB;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Inter', sans-serif; color: var(--text); background: #fff; line-height: 1.75; }}
    a {{ color: var(--teal); }}

    /* NAV */
    nav {{ background: var(--teal); padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }}
    nav a.logo {{ font-family: 'Poppins', sans-serif; font-weight: 700; font-size: 18px; color: #fff; text-decoration: none; }}
    nav a.logo span {{ color: var(--gold); }}
    nav a.back {{ font-size: 13px; color: rgba(255,255,255,0.7); text-decoration: none; }}
    nav a.back:hover {{ color: var(--gold); }}

    /* ARTICLE */
    .article-wrap {{ max-width: 720px; margin: 0 auto; padding: 52px 24px 80px; }}
    .article-meta {{ font-size: 13px; color: var(--text-light); margin-bottom: 12px; }}
    h1 {{ font-family: 'Poppins', sans-serif; font-size: clamp(26px, 4vw, 38px); font-weight: 700; color: var(--teal); line-height: 1.2; margin-bottom: 28px; }}
    h1::after {{ content: ''; display: block; width: 48px; height: 3px; background: var(--gold); margin-top: 16px; }}
    .article-body h2 {{ font-family: 'Poppins', sans-serif; font-size: 20px; font-weight: 700; color: var(--teal); margin: 36px 0 12px; }}
    .article-body p {{ margin-bottom: 18px; font-size: 16px; }}
    .article-body strong {{ font-weight: 600; color: var(--teal); }}

    /* CTA BOX */
    .cta-box {{ margin-top: 52px; padding: 32px; background: var(--teal); border-radius: 16px; text-align: center; }}
    .cta-box p {{ font-family: 'Poppins', sans-serif; font-size: 13px; font-weight: 600; color: var(--gold); letter-spacing: 2px; text-transform: uppercase; margin-bottom: 10px; }}
    .cta-box h3 {{ font-family: 'Poppins', sans-serif; font-size: 20px; font-weight: 700; color: #fff; margin-bottom: 10px; }}
    .cta-box .desc {{ font-size: 14px; color: rgba(255,255,255,0.72); margin-bottom: 22px; }}
    .cta-box a {{ display: inline-block; background: var(--gold); color: var(--teal); font-family: 'Poppins', sans-serif; font-weight: 700; font-size: 14px; padding: 12px 28px; border-radius: 28px; text-decoration: none; }}
    .cta-box a:hover {{ background: #e8c540; }}

    /* BLOG BACK LINK */
    .back-to-blog {{ margin-top: 48px; padding-top: 28px; border-top: 1px solid var(--border); font-size: 14px; }}
    .back-to-blog a {{ color: var(--teal); font-weight: 600; text-decoration: none; }}

    /* FOOTER */
    footer {{ background: var(--teal); color: rgba(255,255,255,0.5); text-align: center; padding: 24px; font-size: 13px; }}
    footer a {{ color: var(--gold); text-decoration: none; }}
  </style>
</head>
<body>

<nav>
  <a class="logo" href="{BASE_URL}">Máš <span>Filipa?</span></a>
  <a class="back" href="{BASE_URL}/blog/">← Všetky články</a>
</nav>

<div class="article-wrap">
  <div class="article-meta">{date_str} &nbsp;·&nbsp; masfilipa.sk</div>
  <h1>{article['title']}</h1>
  <div class="article-body">
    {article['content_html']}
  </div>

  <div class="cta-box">
    <p>Súvisí s týmto článkom</p>
    <h3>{topic['ebook']}</h3>
    <div class="desc">Chceš viac? Celý pohľad, konkrétne nástroje a príbehy z praxe nájdeš v e-booku.</div>
    <a href="{topic['ebook_url']}">Kúpiť e-book za 19,99 €</a>
  </div>

  <div class="back-to-blog">
    <a href="{BASE_URL}/blog/">← Späť na všetky články</a>
    &nbsp;&nbsp;|&nbsp;&nbsp;
    <a href="{BASE_URL}">masfilipa.sk</a>
  </div>
</div>

<footer>
  © 2025 Filip &nbsp;·&nbsp; <a href="{BASE_URL}">masfilipa.sk</a>
</footer>

</body>
</html>"""

def generate_token(slug):
    """Vygeneruje bezpečný token pre schvaľovanie."""
    key = APPROVE_SECRET.encode()
    msg = slug.encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]

def send_approval_email(article, topic, slug, token, full_html):
    """Pošle email s náhľadom a tlačidlami Pridať / Zamietnuť."""
    approve_url = f"{APPROVE_ENDPOINT}?action=approve&slug={slug}&token={token}"
    reject_url  = f"{APPROVE_ENDPOINT}?action=reject&slug={slug}&token={token}"

    # Full article text for email
    preview_text = re.sub(r'<[^>]+>', '', article['content_html'])

    article_html_clean = re.sub(r'<h2([^>]*)>', r'<h3 style="color:#0B3C49;font-size:15px;margin:20px 0 8px;">', article['content_html'])
    article_html_clean = re.sub(r'</h2>', '</h3>', article_html_clean)
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px;">
      <div style="background: #0B3C49; padding: 20px 24px; border-radius: 8px 8px 0 0;">
        <h2 style="color: #D4AF37; margin: 0; font-size: 16px;">📝 Nový článok na schválenie</h2>
        <p style="color: rgba(255,255,255,0.7); margin: 6px 0 0; font-size: 13px;">masfilipa.sk · automatický generátor</p>
      </div>
      <div style="border: 1px solid #dde6ea; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
        <h3 style="color: #0B3C49; margin: 0 0 8px;">{article['title']}</h3>
        <p style="color: #5a5a72; font-size: 13px; margin: 0 0 16px;">URL: <code>/blog/{slug}.html</code></p>
        <p style="color: #888; font-size: 12px; margin: 0 0 4px;">Meta popis:</p>
        <p style="color: #333; font-size: 13px; background: #f8f8f8; padding: 10px; border-radius: 6px; margin: 0 0 20px;">{article['meta_description']}</p>
        <p style="color: #888; font-size: 12px; margin: 0 0 4px;">Náhľad textu:</p>
        <div style="color: #333; font-size: 14px; line-height: 1.75; margin: 0 0 28px; border-left: 3px solid #0B3C49; padding-left: 16px;">{article_html_clean}</div>
        <p style="color: #888; font-size: 12px; margin: 0 0 4px;">Súvisiaci e-book:</p>
        <p style="color: #0B3C49; font-weight: bold; margin: 0 0 28px;">{topic['ebook']}</p>

        <div style="text-align: center; display: flex; gap: 16px; justify-content: center;">
          <a href="{approve_url}" style="background: #0B3C49; color: #fff; padding: 14px 32px; border-radius: 28px; text-decoration: none; font-weight: bold; font-size: 15px;">
            ✅ Pridať na web
          </a>
          <a href="{reject_url}" style="background: #fff; color: #c0392b; padding: 14px 32px; border-radius: 28px; text-decoration: none; font-weight: bold; font-size: 15px; border: 2px solid #c0392b;">
            ❌ Zamietnuť
          </a>
        </div>

        <p style="color: #aaa; font-size: 11px; text-align: center; margin-top: 20px;">
          Tento email bol vygenerovaný automaticky. Tokeny sú platné 7 dní.
        </p>
      </div>
    </div>
    """

    payload = {
        "sender": {"name": "masfilipa.sk", "email": "masfilipa@masfilipa.sk"},
        "to": [{"email": AUTHOR_EMAIL}],
        "subject": f"📝 Nový článok: {article['title']}",
        "htmlContent": html_body,
    }

    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=15
    )
    resp.raise_for_status()
    print(f"Email odoslaný: {resp.status_code}")

def main():
    print("=== masfilipa.sk — generátor článkov ===")
    topic = get_topic_for_week()
    print(f"Téma: {topic['title_hint']}")

    print("Generujem článok...")
    article = generate_article(topic)
    print(f"Titulok: {article['title']}")

    slug = slugify(article['title'])
    date_str = datetime.now().strftime("%-d. %-m. %Y")
    token = generate_token(slug)

    print(f"Slug: {slug}")
    print(f"Token: {token[:8]}...")

    full_html = build_full_html(article, topic, slug, date_str)

    # Ulož dáta pre PHP webhook (GitHub → server cez approve)
    post_data = {
        "slug": slug,
        "title": article['title'],
        "date": date_str,
        "ebook": topic['ebook'],
        "html": full_html,
    }

    # Pošli email
    print("Posielam email...")
    # Zakóduj HTML do base64 pre prenos cez URL (approve endpoint ho dostane z Brevo env)
    import base64
    encoded = base64.b64encode(json.dumps(post_data).encode()).decode()

    # Ulož do súboru pre prípadné debugovanie
    with open('last_post.json', 'w', encoding='utf-8') as f:
        json.dump(post_data, f, ensure_ascii=False, indent=2)

    send_approval_email(article, topic, slug, token, full_html)
    print("✅ Hotovo! Email odoslaný na schválenie.")

if __name__ == '__main__':
    main()
