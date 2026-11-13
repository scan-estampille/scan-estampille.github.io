// Service worker de l'application Estampille Sanitaire CE.
// À CHAQUE mise en ligne, changer VERSION (et APP_VERSION dans index.html, avec la même valeur).
// Ces deux lignes sont aussi réécrites automatiquement par le workflow GitHub « Mise à jour liste Italie ».
const VERSION = '2026-11-13c';

const CACHE = `estampille-${VERSION}`;

// Fichiers mis en cache à l'installation pour fonctionner hors ligne.
// Un fichier absent n'empêche pas l'installation (chaque ajout est tenté séparément).
const PRECACHE = [
  './',
  './index.html',
  './manifest.webmanifest',
  './assets/tailwind.css',
  './assets/lucide-subset.min.js',
  './ETAB_AGR_853.txt',
  './ETAB_AGR_IT.txt',
  './ETAB_AGR_IT.meta.json',
  './icons/favicon.svg',
  './icons/favicon-32.png',
  './icons/apple-touch-icon.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(PRECACHE.map(async (url) => {
      try {
        const res = await fetch(url, { cache: 'reload' });
        if (res.ok) await cache.put(url, res);
      } catch (e) { /* hors ligne ou fichier absent : on continue */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter((n) => n.startsWith('estampille-') && n !== CACHE)
      .map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // Le relais Cloudflare, la DGAL, Google Maps, etc. ne passent pas par le cache
  if (url.origin !== self.location.origin) return;

  // Pages : réseau d'abord (toujours la dernière version), cache si hors ligne
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const res = await fetch(req);
        const cache = await caches.open(CACHE);
        cache.put(req, res.clone());
        return res;
      } catch (e) {
        return (await caches.match(req))
            || (await caches.match('./index.html'))
            || (await caches.match('./'))
            || Response.error();
      }
    })());
    return;
  }

  // Autres fichiers du site (listes, CSS, icônes…) : réponse immédiate depuis le cache,
  // et mise à jour en arrière-plan pour la visite suivante
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(req);
    const network = fetch(req).then((res) => {
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    }).catch(() => null);
    return cached || (await network) || Response.error();
  })());
});
