<?php
/**
 * masfilipa.sk — Blog Approval Webhook
 * Umiestni do: /web/approve_post.php
 *
 * Príjme GET request s action=approve|reject, slug a token.
 * Ak je token platný a action=approve, stiahne HTML z GitHub a uloží ho.
 */

// --- KONFIGURÁCIA ---
// APPROVE_SECRET sa NIKDY nehardkóduje (repo je verejný). Načíta sa z prostredia,
// alebo z gitignorovaného súboru config.local.php umiestneného na serveri.
// Musí byť ROVNAKÝ ako GitHub Actions secret APPROVE_SECRET (generate_post.py).
$APPROVE_SECRET = getenv('APPROVE_SECRET') ?: '';
$GITHUB_TOKEN   = getenv('GITHUB_TOKEN') ?: '';
if (($APPROVE_SECRET === '' || $GITHUB_TOKEN === '') && is_file(__DIR__ . '/config.local.php')) {
    require __DIR__ . '/config.local.php'; // má definovať $APPROVE_SECRET a $GITHUB_TOKEN
}
if (empty($APPROVE_SECRET)) {
    http_response_code(500);
    die('Chyba konfigurácie: chýba APPROVE_SECRET.');
}
$GITHUB_REPO     = 'ChallengeMeNow/masfilipa-blog'; // tvoj GitHub repo
$BLOG_DIR        = __DIR__ . '/blog/';
$LOG_FILE        = __DIR__ . '/approve_log.txt';
$SITEMAP_FILE    = __DIR__ . '/sitemap.xml';        // sitemap v koreni webu
$INDEX_FILE      = __DIR__ . '/blog/index.html';    // listing blogu
$SITE_URL        = 'https://masfilipa.sk';

// --- FUNKCIE ---
function log_msg($msg) {
    global $LOG_FILE;
    file_put_contents($LOG_FILE, date('Y-m-d H:i:s') . ' ' . $msg . "\n", FILE_APPEND);
}

// SK dátum "16. 6. 2026" -> ISO "2026-06-16" (vstup pre <lastmod>)
function sk_date_to_iso($d) {
    $parts = preg_split('/[.\s]+/', trim($d), -1, PREG_SPLIT_NO_EMPTY);
    if (count($parts) < 3) return date('Y-m-d');
    return sprintf('%04d-%02d-%02d', (int)$parts[2], (int)$parts[1], (int)$parts[0]);
}

// Prepíše sitemap.xml z poľa článkov + statické URL (home, blog).
function regenerate_sitemap($posts) {
    global $SITEMAP_FILE, $SITE_URL;

    // zoraď články od najnovšieho po najstarší podľa dátumu
    usort($posts, function ($a, $b) {
        return strcmp(sk_date_to_iso($b['date']), sk_date_to_iso($a['date']));
    });
    $newest = $posts ? sk_date_to_iso($posts[0]['date']) : date('Y-m-d');

    $url = function ($loc, $lastmod, $freq, $pri) {
        return "  <url>\n    <loc>{$loc}</loc>\n    <lastmod>{$lastmod}</lastmod>\n"
             . "    <changefreq>{$freq}</changefreq>\n    <priority>{$pri}</priority>\n  </url>\n";
    };

    $xml  = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    $xml .= "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n";
    $xml .= $url("{$SITE_URL}/",      $newest, 'weekly', '1.0');
    $xml .= $url("{$SITE_URL}/blog/", $newest, 'weekly', '0.9');
    foreach ($posts as $p) {
        $loc = "{$SITE_URL}/blog/" . rawurlencode($p['slug']) . '.html';
        $xml .= $url($loc, sk_date_to_iso($p['date']), 'monthly', '0.8');
    }
    $xml .= "</urlset>\n";

    file_put_contents($SITEMAP_FILE, $xml);
}

// Prepíše zoznam článkov v blog/index.html medzi značkami POSTS:START a POSTS:END.
//
// Listing sa predtým renderoval v prehliadači cez fetch('/blog/posts.json'), takže
// Googlebot na /blog/ videl prázdnu stránku (GSC: "Discovered - currently not
// indexed") a články z nej nedostávali žiadny interný odkaz. Preto sa zoznam
// vypisuje priamo do HTML pri každom schválení — rovnako ako sitemap.xml.
//
// Zvyšok súboru (dizajn, CSS) sa nemení, prepisuje sa len blok medzi značkami.
function regenerate_blog_index($posts) {
    global $INDEX_FILE;

    if (!is_file($INDEX_FILE) || !is_writable($INDEX_FILE)) {
        log_msg("WARN: index.html sa nedá zapísať, listing preskočený");
        return;
    }

    $html = file_get_contents($INDEX_FILE);
    if (strpos($html, 'POSTS:START') === false || strpos($html, 'POSTS:END') === false) {
        log_msg("WARN: v index.html chýbajú značky POSTS:START/END, listing preskočený");
        return;
    }

    usort($posts, function ($a, $b) {
        return strcmp(sk_date_to_iso($b['date']), sk_date_to_iso($a['date']));
    });

    $esc = function ($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); };

    if (!$posts) {
        $cards = '    <div class="empty"><p>Zatiaľ žiadne články.</p><p>Čoskoro pribudnú.</p></div>';
    } else {
        $cards = '';
        foreach ($posts as $p) {
            $href = '/blog/' . rawurlencode($p['slug']) . '.html';
            $cards .= '    <a class="post-card" href="' . $esc($href) . '">' . "\n"
                   .  '      <div class="post-date">' . $esc($p['date']) . "</div>\n"
                   .  '      <div class="post-title">' . $esc($p['title']) . "</div>\n"
                   .  '      <span class="post-ebook">' . $esc($p['ebook']) . "</span>\n"
                   .  '      <span class="post-arrow">&rarr;</span>' . "\n"
                   .  "    </a>\n";
        }
        $cards = rtrim($cards, "\n");
    }

    // Značky ostávajú v súbore, aby sa dal blok prepísať aj nabudúce.
    // preg_replace_callback (nie preg_replace), aby sa $ a \ v titulkoch článkov
    // nebrali ako spätné referencie v náhrade.
    $count = 0;
    $new = preg_replace_callback(
        '/(<!-- POSTS:START.*?-->)(.*?)(<!-- POSTS:END -->)/s',
        function ($m) use ($cards) { return $m[1] . "\n" . $cards . "\n  " . $m[3]; },
        $html,
        1,
        $count
    );

    if ($new === null || $count !== 1) {
        log_msg("WARN: prepis listingu v index.html zlyhal");
        return;
    }
    if (file_put_contents($INDEX_FILE, $new) === false) {
        log_msg("WARN: zápis index.html zlyhal");
        return;
    }
    log_msg("Listing v index.html prepísaný (" . count($posts) . " článkov)");
}

function verify_token($slug, $token, $secret) {
    $expected = substr(hash_hmac('sha256', $slug, $secret), 0, 32);
    return hash_equals($expected, $token);
}

function fetch_article_from_github($slug, $repo) {
    // Stiahne posledný vygenerovaný post z GitHub Actions artifact
    // Jednoduchšie riešenie: post data sú enkódované v URL parametri
    return null;
}

// --- HLAVNÁ LOGIKA ---
$action = isset($_GET['action']) ? $_GET['action'] : '';
$slug   = isset($_GET['slug'])   ? preg_replace('/[^a-z0-9\-]/', '', $_GET['slug']) : '';
$token  = isset($_GET['token'])  ? preg_replace('/[^a-f0-9]/', '', $_GET['token']) : '';
$html_b64 = isset($_GET['html']) ? $_GET['html'] : '';

// Validácia
if (empty($action) || empty($slug) || empty($token)) {
    http_response_code(400);
    die('Neplatný request.');
}

if (!verify_token($slug, $token, $APPROVE_SECRET)) {
    log_msg("UNAUTHORIZED: slug=$slug");
    http_response_code(401);
    die('Neplatný token.');
}

log_msg("ACTION: $action | SLUG: $slug");

if ($action === 'reject') {
    log_msg("REJECTED: $slug");
    ?>
    <!DOCTYPE html><html lang="sk"><head><meta charset="UTF-8">
    <title>Zamietnuté</title>
    <style>body{font-family:sans-serif;text-align:center;padding:60px;color:#333;}
    h2{color:#c0392b;}a{color:#0B3C49;}</style></head><body>
    <h2>❌ Článok zamietnutý</h2>
    <p>Článok <strong><?= htmlspecialchars($slug) ?></strong> nebol pridaný na web.</p>
    <p><a href="https://masfilipa.sk">← Späť na masfilipa.sk</a></p>
    </body></html>
    <?php
    exit;
}

if ($action === 'approve') {
    // HTML príde ako base64 GET parameter (generátor ho pošle cez Brevo link)
    if (empty($html_b64)) {
        // Alternatíva: čítaj z GitHub API (last_post.json)
        $api_url = "https://raw.githubusercontent.com/{$GITHUB_REPO}/main/last_post.json";
        $json_raw = @file_get_contents($api_url);
        if (!$json_raw) {
            log_msg("ERROR: Nemôžem stiahnuť last_post.json z GitHub");
            die('Chyba: Nemôžem načítať obsah článku.');
        }
        $post_data = json_decode($json_raw, true);
    } else {
        $post_data = json_decode(base64_decode($html_b64), true);
    }

    if (!isset($post_data['html']) || !isset($post_data['slug'])) {
        log_msg("ERROR: Neplatný post_data pre slug=$slug");
        die('Chyba: Neplatné dáta článku.');
    }

    // Overíme slug zhodu
    if ($post_data['slug'] !== $slug) {
        log_msg("ERROR: Slug mismatch: expected $slug, got {$post_data['slug']}");
        die('Chyba: Nezhoda slug.');
    }

    // Vytvor blog adresár ak neexistuje
    if (!is_dir($BLOG_DIR)) {
        mkdir($BLOG_DIR, 0755, true);
    }

    // Ulož HTML súbor
    $file_path = $BLOG_DIR . $slug . '.html';
    file_put_contents($file_path, $post_data['html']);

    // Aktualizuj blog index (JSON zoznam článkov)
    $index_file = $BLOG_DIR . 'posts.json';
    $posts = [];
    if (file_exists($index_file)) {
        $posts = json_decode(file_get_contents($index_file), true) ?: [];
    }

    // Pridaj nový post na začiatok (ak ešte neexistuje)
    $exists = false;
    foreach ($posts as $p) {
        if ($p['slug'] === $slug) { $exists = true; break; }
    }

    if (!$exists) {
        array_unshift($posts, [
            'slug'  => $slug,
            'title' => $post_data['title'],
            'date'  => $post_data['date'],
            'ebook' => $post_data['ebook'],
        ]);
        file_put_contents($index_file, json_encode($posts, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
    }

    // Regeneruj sitemap.xml a listing (vždy, nech sedia s aktuálnym posts.json)
    regenerate_sitemap($posts);
    regenerate_blog_index($posts);

    log_msg("APPROVED: $slug → uložený ako $file_path");

    ?>
    <!DOCTYPE html><html lang="sk"><head><meta charset="UTF-8">
    <title>Pridané</title>
    <style>body{font-family:sans-serif;text-align:center;padding:60px;color:#333;}
    h2{color:#0B3C49;}a{color:#0B3C49;font-weight:bold;}</style></head><body>
    <h2>✅ Článok pridaný na web!</h2>
    <p>Článok <strong><?= htmlspecialchars($post_data['title']) ?></strong> je teraz dostupný na:</p>
    <p><a href="https://masfilipa.sk/blog/<?= htmlspecialchars($slug) ?>.html" target="_blank">
      masfilipa.sk/blog/<?= htmlspecialchars($slug) ?>.html</a></p>
    <br>
    <a href="https://masfilipa.sk">← Späť na masfilipa.sk</a>
    </body></html>
    <?php
    exit;
}

if ($action === 'feedback') {
    if (empty($GITHUB_TOKEN)) {
        http_response_code(500);
        die('Chyba konfigurácie: chýba GITHUB_TOKEN v config.local.php.');
    }

    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        $feedback_text = trim($_POST['feedback_text'] ?? '');
        if (empty($feedback_text)) {
            http_response_code(400);
            die('Feedback nesmie byť prázdny.');
        }

        $payload = json_encode([
            'ref'    => 'main',
            'inputs' => [
                'feedback_slug' => $slug,
                'feedback_text' => $feedback_text,
            ],
        ]);

        $api_url = "https://api.github.com/repos/{$GITHUB_REPO}/actions/workflows/generate_post.yml/dispatches";
        $ctx = stream_context_create([
            'http' => [
                'method'  => 'POST',
                'header'  => implode("\r\n", [
                    'Content-Type: application/json',
                    "Authorization: Bearer {$GITHUB_TOKEN}",
                    'Accept: application/vnd.github+json',
                    'X-GitHub-Api-Version: 2022-11-28',
                    'User-Agent: masfilipa-approve-webhook',
                ]),
                'content'         => $payload,
                'ignore_errors'   => true,
            ],
        ]);

        $result = @file_get_contents($api_url, false, $ctx);
        $status_line = $http_response_header[0] ?? '';
        preg_match('/HTTP\/\S+ (\d+)/', $status_line, $m);
        $http_code = (int)($m[1] ?? 0);

        if ($http_code === 204) {
            log_msg("FEEDBACK TRIGGERED: $slug | feedback=" . substr($feedback_text, 0, 80));
            ?>
            <!DOCTYPE html><html lang="sk"><head><meta charset="UTF-8">
            <title>Feedback odoslaný</title>
            <style>body{font-family:sans-serif;text-align:center;padding:60px;color:#333;}
            h2{color:#B8860B;}a{color:#0B3C49;}</style></head><body>
            <h2>💬 Feedback odoslaný!</h2>
            <p>Článok <strong><?= htmlspecialchars($slug) ?></strong> bude prepísaný s tvojím feedbackom.</p>
            <p>Workflow štartuje na GitHub Actions — nový email príde do ~2 minút.</p>
            <br><a href="https://masfilipa.sk">← Späť na masfilipa.sk</a>
            </body></html>
            <?php
        } else {
            log_msg("FEEDBACK ERROR: $slug | http=$http_code | response=" . substr($result, 0, 200));
            http_response_code(502);
            echo "Chyba pri spúšťaní workflow (HTTP {$http_code}). Skús znova alebo kontaktuj admina.";
        }
        exit;
    }

    // GET: zobraz formulár
    ?>
    <!DOCTYPE html><html lang="sk"><head><meta charset="UTF-8">
    <title>Feedback k článku</title>
    <style>
      body{font-family:sans-serif;max-width:600px;margin:60px auto;padding:0 20px;color:#333;}
      h2{color:#B8860B;}
      textarea{width:100%;height:160px;padding:10px;font-size:15px;border:1px solid #ccc;border-radius:4px;resize:vertical;}
      button{margin-top:12px;padding:12px 28px;background:#B8860B;color:#fff;border:none;border-radius:4px;font-size:16px;cursor:pointer;}
      button:hover{background:#9a7008;}
      .hint{font-size:13px;color:#666;margin-top:6px;}
    </style></head><body>
    <h2>💬 Feedback k článku</h2>
    <p>Článok: <strong><?= htmlspecialchars($slug) ?></strong></p>
    <form method="post"
          action="?action=feedback&slug=<?= urlencode($slug) ?>&token=<?= urlencode($token) ?>">
      <textarea name="feedback_text"
                placeholder="Napíš čo chceš zmeniť, napr: Článok nesmie prezrádzať obsah e-booku — iba naznačiť tému a presmerovať čitateľa na stiahnutie. Skráť sekciu o krokov ku koncu."></textarea>
      <p class="hint">Feedback bude pridaný k promptu a článok sa vygeneruje odznova.</p>
      <button type="submit">Odoslať feedback a pregenerovať</button>
    </form>
    <br><a href="https://masfilipa.sk">← Späť na masfilipa.sk</a>
    </body></html>
    <?php
    exit;
}

http_response_code(400);
echo 'Neznáma akcia.';
