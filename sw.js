// Service worker Estampille Sanitaire CE
// Incrémenter VERSION à chaque déploiement pour forcer le renouvellement du cache.
const VERSION = 'v2';
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

// Page : réseau d'abord (4 s max), puis la version en cache
async function handleNavigation(request) {
    const cache = await caches.open(CACHE);
    try {
        const response = await Promise.race([
            fetch(request),
            new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 4000))
        ]);
        if (response.ok) cache.put('./index.html', response.clone());
        return response;
    } catch (e) {
        return (await cache.match('./index.html')) || (await cache.match('./')) || Response.error();
    }
}

// Fichiers statiques : réponse immédiate depuis le cache, mise à jour en arrière-plan
async function handleAsset(request) {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(request, { ignoreSearch: true });
    const network = fetch(request)
        .then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
        })
        .catch(() => null);
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
        event.respondWith(handleNavigation(request));
    } else {
        event.respondWith(handleAsset(request));
    }
});
