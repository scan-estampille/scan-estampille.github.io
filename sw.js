// Service worker Estampille Sanitaire CE
// Incrémenter VERSION à chaque déploiement pour forcer le renouvellement du cache.
// v4 : chaque page est mise en cache sous sa propre adresse (avant, toute page visitée
//      écrasait l'appli enregistrée sous index.html). Le changement de version purge
//      les caches v3 éventuellement corrompus.
// v5 : nouveau CSS (encart de signalement, modale de contact).
// v6 : lecture de plusieurs estampilles (liste avec vignettes).
const VERSION = 'v6';
const CACHE = `estampille-${VERSION}`;

const APP_SHELL = [
    './',
    './index.html',
    './manifest.webmanifest',
    './assets/tailwind.css',
    './assets/lucide-1.59.0.min.js',
    './icons/favicon.svg',
    './icons/favicon-32.png',
    './icons/icon-192.png',
    './icons/icon-512.png',
    './icons/icon-maskable-512.png',
    './icons/apple-touch-icon.png'
];

// Au-delà de ce délai, on sert la copie en cache (si elle existe) sans attendre le réseau
const NETWORK_TIMEOUT_MS = 4000;

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE)
            .then((cache) => cache.addAll(APP_SHELL.map((url) => new Request(url, { cache: 'reload' }))))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k.startsWith('estampille-') && k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

// Adresse de la page sans paramètres ni ancre : /?q=… et / partagent la même entrée
function pageKey(url) {
    return new Request(url.origin + url.pathname);
}

function isAppRoot(url) {
    const scope = new URL(self.registration.scope);
    return url.pathname === scope.pathname || url.pathname === scope.pathname + 'index.html';
}

// Pages : réseau d'abord, copie en cache de CETTE page en secours
async function handleNavigation(event) {
    const { request } = event;
    const url = new URL(request.url);
    const key = pageKey(url);
    const cache = await caches.open(CACHE);

    const network = fetch(request).then((response) => {
        // Les redirections (ex. /etablissement/xx sans « / » final) ne sont pas mises en cache
        if (response.ok && response.type === 'basic' && !response.redirected) {
            cache.put(key, response.clone());
        }
        return response;
    });
    // Le téléchargement continue même si on a déjà répondu avec le cache
    event.waitUntil(network.catch(() => null));

    const cached = (await cache.match(key))
        || (isAppRoot(url) ? (await cache.match('./index.html')) || (await cache.match('./')) : null);

    try {
        if (!cached) return await network; // rien en cache : on attend le réseau, sans délai
        return await Promise.race([
            network,
            new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), NETWORK_TIMEOUT_MS))
        ]);
    } catch (e) {
        if (cached) return cached;
        // Hors ligne sur une page jamais visitée : on propose l'appli, qui fonctionne sans connexion
        return (await cache.match('./index.html')) || (await cache.match('./')) || Response.error();
    }
}

// Fichiers statiques : réponse immédiate depuis le cache, mise à jour en arrière-plan
async function handleAsset(event) {
    const { request } = event;
    const cache = await caches.open(CACHE);
    const cached = await cache.match(request, { ignoreSearch: true });
    const network = fetch(request)
        .then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
        })
        .catch(() => null);
    event.waitUntil(network);
    return cached || (await network) || Response.error();
}

self.addEventListener('fetch', (event) => {
    const { request } = event;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    // Uniquement les fichiers de l'application : le relais OCR, la DGAL, Google Maps et Pappers passent directement
    if (url.origin !== self.location.origin) return;
    // La liste DGAL (copie locale) est déjà conservée dans IndexedDB par l'application
    if (url.pathname.endsWith('.txt')) return;

    if (request.mode === 'navigate') {
        event.respondWith(handleNavigation(event));
    } else {
        event.respondWith(handleAsset(event));
    }
});
