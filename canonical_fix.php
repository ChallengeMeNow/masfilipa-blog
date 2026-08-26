<?php
/**
 * masfilipa.sk — jednorazová kanonizácia duplicitných článkov
 * Umiestni do: /web/canonical_fix.php, spusti raz v prehliadači, potom ZMAŽ.
 *
 * Prečo: prvých 8 týždňov blogu rotovalo len 8 tém, takže každá téma dostala
 * dva až tri články s takmer identickým kľúčovým slovom. Google ich vyhodnotil
 * ako duplikáty — článok manazment-timu-5-chyb... kvôli tomu vypadol z indexu.
 * Skript prepíše <link rel="canonical"> v slabších (starších) článkoch tak, aby
 * ukazoval na silnejší článok z tej istej dvojice. Obsah zostáva nedotknutý,
 * články sú ďalej dostupné — Google len vie, ktorý z nich má hodnotiť.
 *
 * Nové články už tento problém nemajú: generate_post.py má od 26.8.2026 tri
 * long-tail varianty na každú tému (viď TOPICS a get_topic_indexes_for_week).
 *
 * POUŽITIE:
 *   1. https://masfilipa.sk/canonical_fix.php          → len ukáže, čo by spravil
 *   2. https://masfilipa.sk/canonical_fix.php?run=1    → naozaj prepíše súbory
 *   3. Zmaž canonical_fix.php zo servera.
 *
 * Pred každým zápisom sa vytvorí záloha {slug}.html.bak. Skript je idempotentný
 * — opakované spustenie už nič nemení.
 */

$BLOG_DIR = __DIR__ . '/blog/';
$SITE_URL = 'https://masfilipa.sk';

// slabší (starší) článok  =>  silnejší článok, na ktorý má ukazovať canonical.
// Silnejší je vždy novší z dvojice — má lepšie spracovanú tému a v Search
// Console aj reálne impresie (prokrastinácia poz. 4, motivácia poz. 27).
$REDIRECT_MAP = [
    // ako sa rozhodnúť (trojica)
    'ako-sa-rozhodnut-v-praci-ked-nemas-dobru-volbu'
        => 'ako-sa-rozhodnut-v-praci-5-otazok-ktore-pouzivam',
    'ako-sa-rozhodnut-ked-je-kazda-moznost-zla'
        => 'ako-sa-rozhodnut-v-praci-5-otazok-ktore-pouzivam',

    // time management (trojica)
    'time-management-manazer-10-hodin-prace-a-stale-nestihate'
        => 'time-management-manazer-system-zarabaj-vs-buduj',
    'time-management-pre-manazerov-preco-nestihate'
        => 'time-management-manazer-system-zarabaj-vs-buduj',

    // dvojice
    'kedy-vyhodit-zamestnanca-a-preco-to-odkladame-prilis-dlho'
        => 'kedy-vyhodit-zamestnanca-metoda-3-sedeni-z-praxe',
    'karierny-postup-slovensko-kedy-cakat-a-kedy-odist'
        => 'karierny-postup-slovensko-3-roky-som-cakal-zbytocne',
    'manazment-timu-5-chyb-ktore-robia-aj-skuseni-manazeri'
        => 'manazment-timu-preco-dobre-umysly-nestacia',
    'prokrastinacia-v-praci-preco-odkladame-dolezite-veci'
        => 'prokrastinacia-v-praci-ked-vola-nestaci-potrebujes-system',
    'zmena-prace-po-30-strach-alebo-prilezitost'
        => 'zmena-prace-slovensko-moj-skok-do-neznama-po-32',
    'ako-motivovat-zamestnancov-co-funguje-a-co-je-iluzia'
        => 'ako-motivovat-zamestnancov-bez-penazi-pravda-z-praxe',
];

$apply = isset($_GET['run']) && $_GET['run'] === '1';

header('Content-Type: text/plain; charset=utf-8');
echo $apply
    ? "REŽIM: zápis — súbory sa prepisujú\n\n"
    : "REŽIM: náhľad — nič sa nemení (spusti s ?run=1 pre zápis)\n\n";

$changed = $skipped = $failed = 0;

foreach ($REDIRECT_MAP as $from => $to) {
    $path       = $BLOG_DIR . $from . '.html';
    $targetPath = $BLOG_DIR . $to . '.html';

    if (!is_file($path)) {
        echo "CHÝBA   {$from}.html — preskakujem\n";
        $failed++;
        continue;
    }
    // Poistka proti preklepu v mape: nikdy neukazuj na neexistujúci článok.
    if (!is_file($targetPath)) {
        echo "CHÝBA   cieľ {$to}.html — {$from}.html nechávam tak\n";
        $failed++;
        continue;
    }

    $html      = file_get_contents($path);
    $canonical = "{$SITE_URL}/blog/{$to}.html";

    if (strpos($html, 'rel="canonical" href="' . $canonical . '"') !== false) {
        echo "OK      {$from}.html už ukazuje na {$to}.html\n";
        $skipped++;
        continue;
    }

    $updated = preg_replace(
        '~<link rel="canonical" href="[^"]*">~',
        '<link rel="canonical" href="' . $canonical . '">',
        $html,
        1,
        $count
    );

    if ($count !== 1) {
        echo "CHYBA   {$from}.html — nenašiel som <link rel=\"canonical\">\n";
        $failed++;
        continue;
    }

    if (!$apply) {
        echo "ZMENÍM  {$from}.html → {$to}.html\n";
        $changed++;
        continue;
    }

    if (!copy($path, $path . '.bak')) {
        echo "CHYBA   {$from}.html — nepodarilo sa vytvoriť zálohu, nemením\n";
        $failed++;
        continue;
    }
    if (file_put_contents($path, $updated) === false) {
        echo "CHYBA   {$from}.html — zápis zlyhal (záloha .bak zostáva)\n";
        $failed++;
        continue;
    }

    echo "ZMENENÉ {$from}.html → {$to}.html\n";
    $changed++;
}

echo "\n";
echo $apply
    ? "Hotovo: {$changed} zmenených, {$skipped} už v poriadku, {$failed} problémov.\n"
    : "Náhľad: {$changed} na zmenu, {$skipped} už v poriadku, {$failed} problémov.\n";

if ($apply && $failed === 0) {
    echo "\nĎalší krok: zmaž canonical_fix.php zo servera a v Search Console\n";
    echo "daj Request indexing na cieľové články (nie na tie kanonizované).\n";
}
