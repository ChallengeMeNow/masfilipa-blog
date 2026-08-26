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
FEEDBACK_SLUG     = os.environ.get('FEEDBACK_SLUG', '').strip()
FEEDBACK_TEXT     = os.environ.get('FEEDBACK_TEXT', '').strip()

# --- TÉMY ČLÁNKOV ---
# Rotujú automaticky, každý týždeň iná téma.
# Poradie je zámerne prestriedané podľa ebooku (kariéra → ľudia → priority →
# rozhodovanie), aby dva týždne po sebe nevyšla téma z rovnakého okruhu.
# Ebook zároveň slúži ako identifikátor tematického okruhu — články s rovnakým
# ebookom sa navzájom prelinkujú v sekcii "Čítaj aj" (viď fetch_related_posts).
#
# Každá téma má tri VARIANTY. Pri 16 témach a týždennom článku sa téma vracia
# každých 16 týždňov — kým mala jediné primary_keyword, druhý článok si s prvým
# konkuroval o tú istú pozíciu. Stav k 26.8.2026: 8 dvojíc a 2 trojice článkov
# s takmer identickým keywordom, jeden z nich Google vyhodnotil ako duplikát a
# vypadol z indexu. Preto každý návrat témy cieli na iný long-tail dopyt.
# Variant vyberá get_topic_for_week() podľa toho, koľký raz už rotácia prebehla,
# takže rovnaký keyword sa zopakuje najskôr o 48 týždňov.
#
# Keywordy sú zámerne long-tail ("ako viesť tím prvýkrát", nie "manažment tímu").
# Na doméne bez backlinkov sú generické head termy nedosiahnuteľné — články na
# ne sedeli na pozíciách 27–45, teda mimo dohľadu.
TOPICS = [
    # --- kolo 1 ---
    {
        "keywords": "kariérny postup, zmena práce, kariéra, pracovný rast",
        "ebook": "Z kuchyne do riaditeľského kresla",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/20137683-17e6-409f-9855-5837402f7408",
        "variants": [
            {
                "title_hint": "Kariérny postup: kedy čakať a kedy odísť",
                "primary_keyword": "kedy odísť z práce kvôli postupu",
                "angle": "Osobný príbeh čakania na postup. Konkrétne signály kedy má zmysel čakať a kedy je čas odísť. Kariérny postup nie je automatický — treba ho aktívne riadiť.",
            },
            {
                "title_hint": "Sľúbili mi povýšenie a nič sa nestalo — čo teraz",
                "primary_keyword": "sľúbené povýšenie sa nekoná",
                "angle": "Sľub bez dátumu nie je sľub. Ako som to riešil ja a ako to vyzeralo z druhej strany, keď som sľuboval ja. Kedy je odklad legitímny a kedy je to len spôsob, ako ťa udržať.",
            },
            {
                "title_hint": "Ako si vypýtať povýšenie, keď šéf sám od seba mlčí",
                "primary_keyword": "ako požiadať o povýšenie",
                "angle": "Väčšina ľudí čaká, kým si ich niekto všimne. Čo ma ako riaditeľa presvedčilo a čo ma odradilo. Konkrétna príprava na ten rozhovor.",
            },
        ],
    },
    {
        "keywords": "vyhadzovanie zamestnanca, manažment tímu, HR rozhodnutia, slabý výkon",
        "ebook": "Krava na Mount Evereste",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/86eb1eb1-8f5a-4dbc-b293-fcc359fe6596",
        "variants": [
            {
                "title_hint": "Kedy vyhodiť zamestnanca — a prečo to odkladáme príliš dlho",
                "primary_keyword": "kedy dať výpoveď zamestnancovi",
                "angle": "Prečo odkladáme ťažké rozhodnutia o ľuďoch a čo to stojí firmu. Metóda 3 sedení — kde už pri prvom je takmer jasné ako sa to bude vyvíjať. Detaily v ebooku.",
            },
            {
                "title_hint": "Zamestnanec neplní úlohy — čo skúsiť predtým, než ho pustíš",
                "primary_keyword": "zamestnanec neplní úlohy",
                "angle": "Slabý výkon má tri celkom odlišné príčiny a každá sa rieši inak. Ako ich rozlíšiť skôr, než siahneš po výpovedi. Prípad z môjho tímu, kde som sa mýlil.",
            },
            {
                "title_hint": "Ako viesť rozhovor o ukončení pracovného pomeru",
                "primary_keyword": "rozhovor o ukončení pracovného pomeru",
                "angle": "Viedol som ich desiatky a stále je to najťažších pätnásť minút v mesiaci. Čo povedať, čo nikdy nehovoriť a prečo sa to nedá odkomunikovať mailom.",
            },
        ],
    },
    {
        "keywords": "time management, manažment času, produktivita, priority",
        "ebook": "Zarábaj alebo buduj",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/d6153a14-0083-4e88-aa6e-181964b13fe8",
        "variants": [
            {
                "title_hint": "Prečo nestíhaš, aj keď pracuješ desať hodín denne",
                "primary_keyword": "prečo nestíham v práci",
                "angle": "Systém zarábaj vs buduj. Prečo nie je problém čas ale priority. Ako rozoznať čo je dôležité od toho čo je len naliehavé.",
            },
            {
                "title_hint": "Kalendár plný mítingov — ako si vziať späť pracovný deň",
                "primary_keyword": "priveľa mítingov v práci",
                "angle": "Keď mi kalendár prvýkrát zaplnili cudzí ľudia, trvalo mi rok, kým som si ho vzal späť. Čo som zrušil, čo skrátil a čo sa stalo potom.",
            },
            {
                "title_hint": "Naliehavé verzus dôležité — ako to rozlíšiť v reálnom dni",
                "primary_keyword": "naliehavé verzus dôležité úlohy",
                "angle": "Teóriu pozná každý, v utorok o desiatej ju nepoužije nikto. Konkrétna otázka, ktorú si kladiem pri každej požiadavke, čo mi príde.",
            },
        ],
    },
    {
        "keywords": "rozhodovanie, ťažké rozhodnutia, kariéra, životné rozhodnutia",
        "ebook": "Ako sa rozhodnúť, keď sa zdá byť každé rozhodnutie zlé",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/6d78e957-ee7c-4378-b620-252a4c20bf1e",
        "variants": [
            {
                "title_hint": "Ako sa rozhodnúť, keď je každá možnosť zlá",
                "primary_keyword": "ako sa rozhodnúť keď je každá možnosť zlá",
                "angle": "Praktický systém rozhodovania z vlastnej skúsenosti. Prečo paralýza rozhodnutím je horšia ako zlé rozhodnutie. Konkrétne otázky ktoré pomáhajú.",
            },
            {
                "title_hint": "Neviem sa rozhodnúť — ako sa dostať z paralýzy",
                "primary_keyword": "neviem sa rozhodnúť",
                "angle": "Odkladanie rozhodnutia je tiež rozhodnutie, len ho spraví za teba niekto iný. Ako si nastaviť termín a čo robiť, keď informácie nikdy nebudú úplné.",
            },
            {
                "title_hint": "Ako si vybrať medzi dvoma pracovnými ponukami",
                "primary_keyword": "ako si vybrať medzi dvoma ponukami práce",
                "angle": "Plat je najhorší kritérium, aj keď vyzerá najobjektívnejšie. Čo som porovnával ja pri poslednom rozhodovaní a čo by som pridal dnes.",
            },
        ],
    },
    # --- kolo 2 ---
    {
        "keywords": "zmena práce, kariéra po tridsiatke, pracovná zmena, nová práca",
        "ebook": "Z kuchyne do riaditeľského kresla",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/20137683-17e6-409f-9855-5837402f7408",
        "variants": [
            {
                "title_hint": "Zmena práce po tridsiatke — strach alebo príležitosť",
                "primary_keyword": "zmena práce po tridsiatke",
                "angle": "Osobný príbeh zmeny. Prečo strach zo zmeny je normálny ale nesmie rozhodovať. Praktické kroky ako vyhodnotiť či zmena dáva zmysel.",
            },
            {
                "title_hint": "Zmena odboru po desiatich rokoch — čo si vieš zobrať so sebou",
                "primary_keyword": "zmena odboru po rokoch praxe",
                "angle": "Nezačínaš od nuly, aj keď to tak vyzerá. Ktoré zručnosti prešli so mnou z kuchyne do IT a ktoré som musel nechať tak.",
            },
            {
                "title_hint": "Oplatí sa zmeniť prácu? Čo si spočítať pred výpoveďou",
                "primary_keyword": "oplatí sa zmeniť prácu",
                "angle": "Rozdiel v plate je len jedna položka. Čo ešte treba do výpočtu — čas na zabehnutie, stratený kredit, riziko skúšobnej doby. Moje dva prechody.",
            },
        ],
    },
    {
        "keywords": "motivácia zamestnancov, manažment tímu, firemná kultúra, leadership",
        "ebook": "Krava na Mount Evereste",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/86eb1eb1-8f5a-4dbc-b293-fcc359fe6596",
        "variants": [
            {
                "title_hint": "Ako motivovať zamestnancov bez peňazí",
                "primary_keyword": "ako motivovať zamestnancov bez peňazí",
                "angle": "Rozdiel medzi vonkajšou a vnútornou motiváciou v praxi. Čo manažéri robia zle. Malé veci ktoré fungujú lepšie ako bonusy.",
            },
            {
                "title_hint": "Tím stratil ťah — ako ho rozhýbať späť",
                "primary_keyword": "ako zvýšiť motiváciu tímu",
                "angle": "Únava tímu nepríde zo dňa na deň a nedá sa vyriešiť teambuildingom. Čo som skúšal, čo nezabralo a čo nakoniec pohlo vecami.",
            },
            {
                "title_hint": "Prečo bonusy nefungujú tak, ako od nich čakáš",
                "primary_keyword": "fungujú finančné bonusy pre zamestnancov",
                "angle": "Bonus zaberie raz a potom sa stane nárokom. Kde má finančná motivácia zmysel a kde len draho kupuje to, čo si mal vyriešiť inak.",
            },
        ],
    },
    {
        "keywords": "prokrastinácia, odkladanie, produktivita, time management",
        "ebook": "Zarábaj alebo buduj",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/d6153a14-0083-4e88-aa6e-181964b13fe8",
        "variants": [
            {
                "title_hint": "Prokrastinácia v práci — ako s ňou prestať",
                "primary_keyword": "prokrastinácia v práci ako prestať",
                "angle": "Prokrastinácia nie je lenivosť — je to symptóm. Konkrétne techniky z praxe. Prečo systém funguje lepšie ako vôľa.",
            },
            {
                "title_hint": "Odkladám najdôležitejšiu úlohu dňa — prečo a čo s tým",
                "primary_keyword": "odkladanie dôležitých úloh",
                "angle": "Odkladá sa vždy tá istá kategória úloh — nejasné zadanie a viditeľné riziko zlyhania. Ako si úlohu rozobrať tak, aby sa dala začať.",
            },
            {
                "title_hint": "Nie je to lenivosť — je to zle zadaná úloha",
                "primary_keyword": "prečo prokrastinujem v práci",
                "angle": "Keď mi v tíme niekto dlho neodovzdal prácu, chyba bola takmer vždy v zadaní, nie v človeku. Ako to platí aj na úlohy, ktoré zadávaš sám sebe.",
            },
        ],
    },
    {
        "keywords": "zostať alebo odísť, dať výpoveď, nespokojnosť v práci, rozhodovanie",
        "ebook": "Ako sa rozhodnúť, keď sa zdá byť každé rozhodnutie zlé",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/6d78e957-ee7c-4378-b620-252a4c20bf1e",
        "variants": [
            {
                "title_hint": "Mám dať výpoveď alebo zostať? Ako to rozhodnúť bez ľútosti",
                "primary_keyword": "mám dať výpoveď alebo zostať",
                "angle": "Najčastejšia otázka, ktorú dostávam. Prečo väčšina ľudí odchádza od človeka, nie od práce — a ako to rozlíšiť. Test, ktorý som si spravil sám predtým, než som odišiel.",
            },
            {
                "title_hint": "Odchádzaš od šéfa alebo od práce? Ako to rozlíšiť",
                "primary_keyword": "zlý šéf dať výpoveď",
                "angle": "Rovnaká práca pod iným človekom je iná práca. Ako zistiť, či problém odíde s tebou do ďalšej firmy, alebo zostane tu.",
            },
            {
                "title_hint": "Kedy dať výpoveď — signály, ktoré som u seba prehliadol",
                "primary_keyword": "kedy dať výpoveď v práci",
                "angle": "Nie deň, keď to praskne, ale mesiace predtým. Tri veci, ktoré som u seba videl a vysvetlil si ich ako únavu.",
            },
        ],
    },
    # --- kolo 3 ---
    {
        "keywords": "zvýšenie platu, vyjednávanie o plate, žiadosť o zvýšenie, kariéra",
        "ebook": "Z kuchyne do riaditeľského kresla",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/20137683-17e6-409f-9855-5837402f7408",
        "variants": [
            {
                "title_hint": "Ako si vypýtať zvýšenie platu — z pohľadu toho, kto rozhoduje",
                "primary_keyword": "ako si vypýtať zvýšenie platu",
                "angle": "Sedel som na druhej strane stola pri desiatkach takýchto rozhovorov. Čo funguje, čo ma odradí za tridsať sekúnd a prečo je načasovanie dôležitejšie než argumenty.",
            },
            {
                "title_hint": "Šéf mi zamietol zvýšenie platu — čo ďalej",
                "primary_keyword": "zamietnuté zvýšenie platu",
                "angle": "Nie každé nie znamená to isté. Ako z odpovede vyčítať, či ide o rozpočet, o načasovanie alebo o teba — a čo si vypýtať namiesto peňazí.",
            },
            {
                "title_hint": "Kedy je najlepší čas žiadať o zvýšenie platu",
                "primary_keyword": "kedy žiadať o zvýšenie platu",
                "angle": "Existujú týždne v roku, keď je odpoveď nie bez ohľadu na to, aký si dobrý. Ako vyzerá rozpočtový cyklus zvnútra a kedy má zmysel prísť.",
            },
        ],
    },
    {
        "keywords": "manažment tímu, riadenie ľudí, leadership, chyby manažéra",
        "ebook": "Krava na Mount Evereste",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/86eb1eb1-8f5a-4dbc-b293-fcc359fe6596",
        "variants": [
            {
                "title_hint": "Chyby začínajúceho manažéra, ktoré robia aj skúsení",
                "primary_keyword": "chyby začínajúceho manažéra",
                "angle": "Konkrétne chyby z vlastnej kariéry. Čo by som robil inak. Prečo dobré úmysly nestačia bez systému.",
            },
            {
                "title_hint": "Prvýkrát vediem tím — čo som si mal ustrážiť na začiatku",
                "primary_keyword": "ako viesť tím prvýkrát",
                "angle": "Prvých deväťdesiat dní rozhodne o tom, ako s tebou budú ľudia hovoriť ďalšie dva roky. Čo som podcenil a čo by som dnes spravil hneď v prvom týždni.",
            },
            {
                "title_hint": "Ako viesť bývalých kolegov, keď sa z teba stane ich šéf",
                "primary_keyword": "povýšenie na šéfa kolegov",
                "angle": "Najnepríjemnejší prechod v kariére. Čo sa musí povedať nahlas hneď na začiatku a prečo snaha zostať kamarátom uškodí obom stranám.",
            },
        ],
    },
    {
        "keywords": "vyhorenie, pracovné vyčerpanie, preťaženie, manažment záťaže",
        "ebook": "Zarábaj alebo buduj",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/d6153a14-0083-4e88-aa6e-181964b13fe8",
        # Zdravotne citlivá téma — všetky varianty musia zostať v manažérskej rovine.
        "variants": [
            {
                "title_hint": "Vyhorenie v tíme — ako som ho prehliadol u seba aj u iných",
                "primary_keyword": "vyhorenie v tíme",
                "angle": "PÍŠ VÝHRADNE Z POZÍCIE MANAŽÉRSKEJ SKÚSENOSTI, nie ako zdravotné rady. Žiadne diagnózy ani liečba. Signály, ktoré som prehliadol u ľudí v tíme, a čo sa v organizácii dá zmeniť. Ak niekto potrebuje pomoc, patrí to k odborníkovi — spomeň to v článku.",
            },
            {
                "title_hint": "Preťažený zamestnanec — signály, ktoré vidno skôr než odíde",
                "primary_keyword": "preťažený zamestnanec signály",
                "angle": "PÍŠ VÝHRADNE Z POZÍCIE MANAŽÉRA, žiadne diagnózy ani zdravotné rady. Čo sa dá všimnúť na práci, nie na človeku — kvalita, komunikácia, tempo. Ako sa spýtať, aby to nebolo výsluchom. Ak ide o zdravie, patrí to k odborníkovi — spomeň to.",
            },
            {
                "title_hint": "Čo sa dá v tíme zmeniť, kým je ešte čas",
                "primary_keyword": "prevencia vyhorenia v tíme",
                "angle": "PÍŠ VÝHRADNE Z POZÍCIE MANAŽÉRA, žiadne diagnózy ani liečba. Organizačné veci, ktoré reálne uberajú záťaž — rozsah zodpovednosti, jasné priority, právo povedať nie. Čo som zaviedol a čo z toho vydržalo. Ak niekto potrebuje pomoc, patrí to k odborníkovi.",
            },
        ],
    },
    {
        "keywords": "povedať nie, odmietnutie úlohy, hranice v práci, preťaženie",
        "ebook": "Ako sa rozhodnúť, keď sa zdá byť každé rozhodnutie zlé",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/6d78e957-ee7c-4378-b620-252a4c20bf1e",
        "variants": [
            {
                "title_hint": "Ako povedať nie šéfovi bez toho, aby si si uškodil",
                "primary_keyword": "ako povedať nie šéfovi",
                "angle": "Ako riaditeľ som si vážil ľudí, ktorí vedeli povedať nie — ak to vedeli povedať správne. Rozdiel medzi 'nemám čas' a 'toto vypadne, ak to zoberiem'. Konkrétne vety.",
            },
            {
                "title_hint": "Mám priveľa práce — ako to povedať šéfovi",
                "primary_keyword": "priveľa práce ako to povedať šéfovi",
                "angle": "Sťažnosť sa dá ignorovať, zoznam s termínmi nie. Ako prísť s číslami namiesto pocitov a nechať rozhodnutie o prioritách na tom, kto ho má robiť.",
            },
            {
                "title_hint": "Ako odmietnuť úlohu a nezostať za lenivého",
                "primary_keyword": "ako odmietnuť úlohu v práci",
                "angle": "Odmietnutie bez alternatívy vyzerá ako nezáujem. Trojkroková veta, ktorú používam dodnes — a jeden prípad, keď som ju mal použiť a nepoužil.",
            },
        ],
    },
    # --- kolo 4 ---
    {
        "keywords": "kariéra bez vysokej školy, práca bez titulu, povýšenie, prax verzus škola",
        "ebook": "Z kuchyne do riaditeľského kresla",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/20137683-17e6-409f-9855-5837402f7408",
        "variants": [
            {
                "title_hint": "Kariéra bez vysokej školy — čo naozaj rozhoduje pri povýšení",
                "primary_keyword": "kariéra bez vysokej školy",
                "angle": "Začínal som v kuchyni a skončil ako technický riaditeľ. Kedy titul reálne rozhodoval a kedy vôbec nie. Čo som musel dokazovať namiesto neho.",
            },
            {
                "title_hint": "Pohovor bez vysokej školy — ako to zohrať",
                "primary_keyword": "pohovor bez vysokej školy",
                "angle": "Sedel som na strane, ktorá vyberá. Kedy som titul riešil a kedy ma zaujímalo úplne niečo iné. Ako o chýbajúcej škole hovoriť tak, aby to nebola obhajoba.",
            },
            {
                "title_hint": "Rozhoduje pri povýšení prax alebo vysoká škola",
                "primary_keyword": "prax alebo vysoká škola",
                "angle": "Odpoveď sa mení podľa toho, ako vysoko si v hierarchii. Kde je titul filter na vstupe a kde už dávno nikoho nezaujíma.",
            },
        ],
    },
    {
        "keywords": "spätná väzba, kritika zamestnanca, hodnotiaci rozhovor, manažment ľudí",
        "ebook": "Krava na Mount Evereste",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/86eb1eb1-8f5a-4dbc-b293-fcc359fe6596",
        "variants": [
            {
                "title_hint": "Ako dať negatívnu spätnú väzbu, aby si človeka nestratil",
                "primary_keyword": "ako dať negatívnu spätnú väzbu",
                "angle": "Konkrétny rozhovor, ktorý som pokazil, a čo ma naučil. Kedy dať spätnú väzbu hneď a kedy počkať. Prečo forma rozhoduje viac než obsah.",
            },
            {
                "title_hint": "Hodnotiaci rozhovor, po ktorom človek neodchádza zlomený",
                "primary_keyword": "ako viesť hodnotiaci rozhovor",
                "angle": "Raz ročne zhrnúť dvanásť mesiacov je nezmysel, ak sa celý rok mlčalo. Ako si rozhovor pripraviť a čo v ňom nemá čo hľadať.",
            },
            {
                "title_hint": "Prečo je sendvičová metóda zlá rada",
                "primary_keyword": "sendvičová metóda spätnej väzby",
                "angle": "Ľudia si zapamätajú len chlieb. Čo som používal namiesto toho a prečo je jasná veta milosrdnejšia než obalená.",
            },
        ],
    },
    {
        "keywords": "delegovanie, delegovanie úloh, manažment času, riadenie tímu",
        "ebook": "Zarábaj alebo buduj",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/d6153a14-0083-4e88-aa6e-181964b13fe8",
        "variants": [
            {
                "title_hint": "Prečo nevieš delegovať — a čo ťa to stojí",
                "primary_keyword": "prečo neviem delegovať",
                "angle": "Nedelegujeme z nedôvery, ale zo strachu, že to bude horšie. Prečo je 'rýchlejšie si to spraviť sám' najdrahšia veta v manažmente. Ako som sa to učil.",
            },
            {
                "title_hint": "Zadal som úlohu a aj tak ju robím sám",
                "primary_keyword": "ako správne zadať úlohu",
                "angle": "Keď sa práca vracia zle spravená, chyba býva v zadaní. Čo musí obsahovať, aby sa nemuselo dovysvetľovať — a prečo termín nie je to najdôležitejšie.",
            },
            {
                "title_hint": "Mikromanažment — ako som sa ho odnaučil",
                "primary_keyword": "mikromanažment ako prestať",
                "angle": "Kontrolovať každý detail je pohodlné, lebo to vyzerá ako zodpovednosť. Čo som prestal kontrolovať ako prvé a čo sa reálne stalo.",
            },
        ],
    },
    {
        "keywords": "riziko v kariére, kariérny risk, istota verzus príležitosť, zmena kariéry",
        "ebook": "Ako sa rozhodnúť, keď sa zdá byť každé rozhodnutie zlé",
        "ebook_url": "https://masfilipa.lemonsqueezy.com/checkout/buy/6d78e957-ee7c-4378-b620-252a4c20bf1e",
        "variants": [
            {
                "title_hint": "Kedy v kariére riskovať a kedy zostať pri istote",
                "primary_keyword": "kedy v kariére riskovať",
                "angle": "Nie každý risk sa oplatí. Ako rozlíšiť risk, ktorý sa dá uniesť, od toho, ktorý ťa položí. Moje dva — jeden vyšiel, druhý nie.",
            },
            {
                "title_hint": "Istá práca verzus lákavá ponuka — ako to vyhodnotiť",
                "primary_keyword": "istota alebo lepšia príležitosť v práci",
                "angle": "Istota má cenu, ktorú si väčšinou nespočítame. Ako si ju vyčísliť a porovnať s tým, čo ponuka reálne sľubuje — a čo len naznačuje.",
            },
            {
                "title_hint": "Risk, ktorý sa mi nevyplatil — a čo ma naučil",
                "primary_keyword": "neúspešná zmena kariéry",
                "angle": "Konkrétny zlý ťah, ktorý ma stál rok. Čo som prehliadol pri rozhodovaní a aké tri otázky si odvtedy kladiem, kým poviem áno.",
            },
        ],
    },
]

# Pevný pondelok, od ktorého sa počítajú týždne. Rotácia sa zámerne neviaže na
# číslo ISO týždňa: to sa na prelome roka vráti na 1, takže po 52. týždni by
# rotácia preskočila späť a zopakovala tú istú tému aj ten istý variant po
# štyroch týždňoch. Priebežné číslo týždňa rastie stále a pár (téma, variant)
# sa tak zopakuje presne raz za 16 * 3 = 48 týždňov.
WEEK_EPOCH = datetime(2026, 4, 13)

def get_topic_indexes_for_week():
    """Vráti (topic_index, variant_index) pre aktuálny týždeň.

    Téma rotuje po týždňoch, variant sa mení až po prejdení celého kola tém.
    Oboje sa ukladá do last_post.json, aby regenerácia po feedbacku vrátila
    presne tú istú tému aj variant."""
    week_index = (datetime.now() - WEEK_EPOCH).days // 7
    topic_index = week_index % len(TOPICS)
    round_num = week_index // len(TOPICS)
    variant_index = round_num % len(TOPICS[topic_index]['variants'])
    return topic_index, variant_index

def resolve_topic(topic_index, variant_index):
    """Zloží tému a jej variant do jedného plochého dictu.

    Zvyšok skriptu tak pracuje s témou rovnako ako predtým, než varianty
    pribudli — title_hint, primary_keyword a angle prídu z variantu, keywords,
    ebook a ebook_url sú spoločné pre celú tému."""
    topic = TOPICS[topic_index]
    variants = topic['variants']
    variant = variants[variant_index % len(variants)]
    return {**{k: v for k, v in topic.items() if k != 'variants'}, **variant}

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

# Tool schema — Claude API garantuje že tool input bude validný JSON podľa tejto schémy.
# Nahrádza pôvodný "vráť JSON v prompte" prístup, ktorý padol 8.6.2026 na nevalidnom JSON.
SUBMIT_ARTICLE_TOOL = {
    "name": "submit_article",
    "description": "Odovzdá vygenerovaný blog článok v štruktúrovanej forme.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Titulok článku, max 60 znakov, obsahuje primárne kľúčové slovo.",
            },
            "meta_description": {
                "type": "string",
                "description": "Popis pre Google, max 155 znakov, obsahuje kľúčové slovo.",
            },
            "content_html": {
                "type": "string",
                "description": "HTML obsah článku s <h2> a <p> tagmi. BEZ html/body/head tagov.",
            },
        },
        "required": ["title", "meta_description", "content_html"],
    },
}


def generate_article(topic, feedback=None, existing_titles=None):
    """Zavolá Claude API cez tool use — schema garantuje validný JSON output."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    feedback_note = ''
    if feedback:
        feedback_note = f"""

DÔLEŽITÉ — PREPÍSANÁ VERZIA:
Predchádzajúca verzia tohto článku bola zamietnutá. Feedback od autora:
"{feedback}"
Zohľadni tento feedback. Zachovaj tému a kľúčové slová, ale uprav obsah podľa pokynov vyššie."""

    dedup_note = ''
    if existing_titles:
        titles_list = '\n'.join(f'- {t}' for t in existing_titles)
        dedup_note = f"""

UŽ EXISTUJÚCE ČLÁNKY — NEDUPLIKUJ:
Na blogu už vyšli tieto články:
{titles_list}
Témy sa periodicky opakujú, preto zvoľ SVIEŽI, odlišný uhol a titulok, ktorý sa
tematicky neprekrýva so žiadnym z článkov vyššie. NEPOUŽI rovnaký ani takmer
rovnaký titulok (napr. len pridaním slov ako "príliš dlho"). Ak by si o tejto téme
mal písať znova, nájdi konkrétny pod-aspekt, ktorý ešte nebol pokrytý."""

    prompt = f"""Si Filip — technický riaditeľ, konzultant a autor e-bookov na masfilipa.sk.
Píšeš po slovensky, priamym osobným štýlom. Žiadna teória, len skúsenosti z praxe.

Napíš blog post na tému: "{topic['title_hint']}"
Uhol pohľadu: {topic['angle']}
Primárne kľúčové slovo (MUSÍ byť v titulku a prvom odstavci): {topic['primary_keyword']}
Sekundárne kľúčové slová (použi prirodzene v texte 2-3x): {topic['keywords']}

POŽIADAVKY:
- Dĺžka: 700-900 slov
- Jazyk: slovenčina, hovorový ale profesionálny štýl
- Štruktúra: krátky úvod (1-2 odstavce, obsahuje primárne kľúčové slovo) → hlavný obsah (5-6 odstavcov s konkrétnymi príkladmi) → záver s výzvou k akcii
- Použi 4-5 medzititulkov (H2) — jeden H2 musí obsahovať primárne kľúčové slovo alebo jeho variáciu
- Každý odstavec musí priniesť konkrétnu hodnotu — žiadne odstavce "na vyplnenie"
- Osobné príbehy a konkrétne príklady, žiadne frázy
- KĽÚČOVÉ: článok má vzbudiť záujem o e-book, ale NESMIE prezradiť jeho obsah — žiadne konkrétne techniky ani systémy z e-booku, len naznač že existujú
- Dávaj pozor na správnu slovenčinu: napr. "štyri mesiace" nie "štyroch mesiacov" v nominatíve
- Na konci NIČ o e-booku — to doplníme automaticky{feedback_note}{dedup_note}

Odošli článok zavolaním nástroja `submit_article`."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=3500,
        tools=[SUBMIT_ARTICLE_TOOL],
        tool_choice={"type": "tool", "name": "submit_article"},
        messages=[{"role": "user", "content": prompt}],
    )

    # tool_choice="tool" forsuje model aby zavolal submit_article — block.input je už dict
    for block in message.content:
        if block.type == "tool_use" and block.name == "submit_article":
            return block.input

    raise RuntimeError(
        f"Claude nevrátil tool_use block. Stop reason: {message.stop_reason}"
    )

def build_full_html(article, topic, slug, date_str, related_posts=None):
    """Zostaví kompletný HTML súbor pre blog post."""
    # Sekcia interného prelinkovania — zobrazí sa len ak existujú iné články
    if related_posts:
        related_links = '\n    '.join(
            f'<a href="{BASE_URL}/blog/{p["slug"]}.html">{p["title"]}</a>'
            for p in related_posts
        )
        related_html = f'''
  <div class="related-posts">
    <p class="related-label">Čítaj aj</p>
    {related_links}
  </div>'''
    else:
        related_html = ''

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

    /* RELATED POSTS */
    .related-posts {{ margin-top: 48px; padding: 28px; background: var(--off-white); border-radius: 12px; border: 1.5px solid var(--border); }}
    .related-label {{ font-family: 'Poppins', sans-serif; font-size: 11px; font-weight: 700; color: var(--gold); letter-spacing: 3px; text-transform: uppercase; margin-bottom: 14px; }}
    .related-posts a {{ display: block; color: var(--teal); font-weight: 600; text-decoration: none; font-size: 15px; padding: 10px 0; border-bottom: 1px solid var(--border); }}
    .related-posts a:last-child {{ border-bottom: none; padding-bottom: 0; }}
    .related-posts a:hover {{ color: var(--gold); }}
    .related-posts a::after {{ content: ' →'; }}

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

  {related_html}

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
  © {datetime.now().year} Filip &nbsp;·&nbsp; <a href="{BASE_URL}">masfilipa.sk</a>
</footer>

</body>
</html>"""

def fetch_existing_titles():
    """Stiahne posts.json a vráti zoznam titulkov existujúcich článkov.
    Slúži na dedup v prompte — Claude nesmie vygenerovať takmer rovnaký článok.
    Pri zlyhaní vráti prázdny zoznam — generovanie pokračuje bez dedup ochrany."""
    try:
        resp = requests.get(f'{BASE_URL}/blog/posts.json', timeout=5)
        resp.raise_for_status()
        return [p.get('title', '') for p in resp.json() if p.get('title')]
    except Exception as e:
        print(f"Upozornenie: nepodarilo sa načítať existujúce titulky ({e})")
        return []

def fetch_related_posts(current_slug, ebook, count=3):
    """Stiahne posts.json zo servera a vráti `count` článkov na prelinkovanie.

    Prednosť majú články z rovnakého tematického okruhu (= rovnaký ebook), aby
    okruh tvoril prepojený celok. Dôvod zmeny: posts.json je zoradený od
    najnovšieho, takže pôvodné `related[:count]` odkazovalo z každého článku na
    tie isté dva najnovšie. Starším článkom neprichádzal žiadny interný odkaz a
    Google ich vypadával z indexu (stav "Crawled - currently not indexed").

    Pri akomkoľvek zlyhaní vráti prázdny zoznam — generovanie pokračuje bez prelinkenia."""
    try:
        resp = requests.get(f'{BASE_URL}/blog/posts.json', timeout=5)
        resp.raise_for_status()
        posts = resp.json()
        # posts.json udržiava zoradené approve_post.php (najnovší prvý) → reversed = najstarší prvý
        candidates = [p for p in reversed(posts) if p.get('slug') != current_slug]
        same_topic = [p for p in candidates if p.get('ebook') == ebook]
        others     = [p for p in candidates if p.get('ebook') != ebook]

        # (count - 1) slotov pre články z rovnakého okruhu. Výber je náhodný, ale
        # seedovaný slugom — pre ten istý článok vyjde vždy rovnako (opakované
        # generovanie po feedbacku dá tie isté odkazy), a naprieč týždňami sa odkazy
        # rozložia na celý okruh. Brať fixne "tie najstaršie" nefunguje: rovnaké dva
        # články by dostávali odkazy stále dokola a stredne staré nikdy žiadny.
        # Posledný slot patrí najnovšiemu článku z iného okruhu, aby čerstvý článok
        # dostal interný odkaz hneď v nasledujúcom týždni a nezostal sirotou.
        picked = random.Random(current_slug).sample(same_topic, min(count - 1, len(same_topic)))
        if others:
            picked.append(others[-1])
        # Doplnenie, ak je okruh malý alebo archív krátky (napr. prvé týždne blogu).
        for p in same_topic + others[::-1]:
            if len(picked) >= count:
                break
            if p['slug'] not in {q['slug'] for q in picked}:
                picked.append(p)
        return picked[:count]
    except Exception as e:
        print(f"Upozornenie: nepodarilo sa načítať related posts ({e})")
        return []

def generate_token(slug):
    """Vygeneruje bezpečný token pre schvaľovanie."""
    key = APPROVE_SECRET.encode()
    msg = slug.encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]

def send_approval_email(article, topic, slug, token, full_html, feedback=None):
    """Pošle email s náhľadom a tlačidlami Pridať / Zamietnuť."""
    approve_url   = f"{APPROVE_ENDPOINT}?action=approve&slug={slug}&token={token}"
    reject_url    = f"{APPROVE_ENDPOINT}?action=reject&slug={slug}&token={token}"
    feedback_url  = f"{APPROVE_ENDPOINT}?action=feedback&slug={slug}&token={token}"

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

        <div style="text-align: center; display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
          <a href="{approve_url}" style="background: #0B3C49; color: #fff; padding: 14px 28px; border-radius: 28px; text-decoration: none; font-weight: bold; font-size: 15px;">
            ✅ Pridať na web
          </a>
          <a href="{feedback_url}" style="background: #fff; color: #D4AF37; padding: 14px 28px; border-radius: 28px; text-decoration: none; font-weight: bold; font-size: 15px; border: 2px solid #D4AF37;">
            💬 Opraviť
          </a>
          <a href="{reject_url}" style="background: #fff; color: #c0392b; padding: 14px 28px; border-radius: 28px; text-decoration: none; font-weight: bold; font-size: 15px; border: 2px solid #c0392b;">
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

    week_topic_index, week_variant_index = get_topic_indexes_for_week()

    if FEEDBACK_SLUG and FEEDBACK_TEXT:
        print(f"Feedback mód: regenerujem '{FEEDBACK_SLUG}'")
        with open('last_post.json', encoding='utf-8') as f:
            last = json.load(f)
        topic_index = last.get('topic_index', week_topic_index)
        # Články spred zavedenia variantov variant_index nemajú — vtedy variant 0,
        # čo je pôvodná definícia témy.
        variant_index = last.get('variant_index', 0)
        feedback = FEEDBACK_TEXT
    else:
        topic_index, variant_index = week_topic_index, week_variant_index
        feedback = None

    topic = resolve_topic(topic_index, variant_index)

    print(f"Téma: {topic['title_hint']} (variant {variant_index + 1})")
    print(f"Kľúčové slovo: {topic['primary_keyword']}")

    existing_titles = fetch_existing_titles()
    print(f"Existujúce články (dedup): {len(existing_titles)}")

    print("Generujem článok...")
    article = generate_article(topic, feedback=feedback, existing_titles=existing_titles)
    print(f"Titulok: {article['title']}")

    slug = slugify(article['title'])
    date_str = datetime.now().strftime("%-d. %-m. %Y")
    token = generate_token(slug)

    print(f"Slug: {slug}")
    print(f"Token: {token[:8]}...")

    print("Načítavam súvisiace články...")
    related_posts = fetch_related_posts(slug, topic['ebook'])
    print(f"Súvisiace články: {len(related_posts)}")

    full_html = build_full_html(article, topic, slug, date_str, related_posts)

    # Ulož dáta pre PHP webhook (GitHub → server cez approve)
    post_data = {
        "slug": slug,
        "title": article['title'],
        "date": date_str,
        "ebook": topic['ebook'],
        "topic_index": topic_index,
        "variant_index": variant_index,
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

    send_approval_email(article, topic, slug, token, full_html, feedback=feedback)
    print("✅ Hotovo! Email odoslaný na schválenie.")

if __name__ == '__main__':
    main()
