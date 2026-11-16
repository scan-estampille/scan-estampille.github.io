// Traduction de l'interface, à la manière de l'option « Traduire » de Chrome.
//
// Le texte d'origine (français) reste dans index.html. Quand une autre langue est choisie, les textes
// visibles, les infobulles et les libellés d'accessibilité sont envoyés au relais (POST /translate),
// qui les fait traduire par une IA et garde les traductions en cache. Le navigateur les garde aussi :
// une langue déjà utilisée s'affiche ensuite sans attente ni requête.
//
// Ce qui n'est JAMAIS envoyé :
//   - tout élément marqué translate="no" (noms, adresses et numéros des établissements, champs saisis…) ;
//   - les passages entourés par l'appli des caractères invisibles U+2068 … U+2069 (fonction data() de
//     index.html) : recherches tapées, numéros lus. Ils sont remplacés par un repère <d0/> avant l'envoi.
// Les textes ajoutés ensuite par l'appli (messages, résultats) sont traduits au fil de l'eau.
(function () {
    'use strict';

    const SOURCE = 'fr';
    const CACHE_VERSION = 1;              // à changer pour oublier les traductions gardées dans le navigateur
    const STORE_KEY = 'langue';
    const BATCH_STRINGS = 40;             // limites d'une requête (le relais refuse au-delà de 60 / 8000)
    const BATCH_CHARS = 6000;
    const ENDPOINT = (document.currentScript && document.currentScript.dataset.endpoint) || '';

    // Noms des langues dans leur propre langue, triés comme dans les menus habituels
    const LANGS = [
        ['ca', 'Català'], ['cs', 'Čeština'], ['da', 'Dansk'], ['de', 'Deutsch'], ['et', 'Eesti'],
        ['en', 'English'], ['es', 'Español'], ['fr', 'Français'], ['ga', 'Gaeilge'], ['hr', 'Hrvatski'],
        ['it', 'Italiano'], ['lv', 'Latviešu'], ['lt', 'Lietuvių'], ['hu', 'Magyar'], ['mt', 'Malti'],
        ['nl', 'Nederlands'], ['nb', 'Norsk bokmål'], ['pl', 'Polski'], ['pt', 'Português'], ['ro', 'Română'],
        ['sk', 'Slovenčina'], ['sl', 'Slovenščina'], ['fi', 'Suomi'], ['sv', 'Svenska'], ['tr', 'Türkçe'],
        ['el', 'Ελληνικά'], ['bg', 'Български'], ['uk', 'Українська']
    ];
    const SUPPORTED = new Set(LANGS.map(l => l[0]));

    const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
    const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'PRE', 'CODE', 'IFRAME', 'TEMPLATE']);
    // Mise en forme à l'intérieur d'une phrase : la phrase est traduite d'un bloc, balises comprises
    const INLINE = new Set(['STRONG', 'B', 'EM', 'I', 'SMALL', 'ABBR', 'SPAN', 'A', 'BR', 'SUB', 'SUP', 'U', 'MARK']);
    const HAS_WORD = /\p{L}{2}/u;
    const DATA_RE = /\u2068([\s\S]*?)\u2069/g;

    let lang = SOURCE;
    let observer = null;
    let cache = new Map();                // texte source → traduction, pour la langue courante
    const pending = new Set();            // textes à demander au relais
    const inflight = new Set();
    const failed = new Set();             // échecs de cette session : on ne redemande pas en boucle
    let flushTimer = null, saveTimer = null, renderQueued = false;

    // État d'origine des nœuds traduits
    const textState = new WeakMap();      // nœud texte → { orig, applied }
    const unitState = new WeakMap();      // élément « phrase » → { nodes, src, lead, trail, applied }
    const attrState = new WeakMap();      // élément → { attr: { orig, applied } }
    let titleState = null;

    // ── Cache du navigateur ─────────────────────────────────────────────────

    function storeKey(l) { return `trad:v${CACHE_VERSION}:${l}`; }
    function loadCache(l) {
        try { return new Map(Object.entries(JSON.parse(localStorage.getItem(storeKey(l)) || '{}'))); }
        catch (e) { return new Map(); }
    }
    function saveCacheSoon() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => {
            try {
                // On garde au plus 3000 textes par langue (les plus récents)
                const entries = [...cache.entries()].slice(-3000);
                localStorage.setItem(storeKey(lang), JSON.stringify(Object.fromEntries(entries)));
            } catch (e) { /* stockage plein ou interdit : la traduction marche quand même */ }
        }, 500);
    }

    // ── Préparation des textes ──────────────────────────────────────────────

    // Remplace les données (U+2068 … U+2069) par des repères <dN/> : elles ne partent pas au relais
    function protect(text) {
        const values = [];
        const src = text.replace(DATA_RE, (_, v) => { values.push(v); return `<d${values.length - 1}/>`; });
        return { src, values };
    }
    function unprotect(text, values) {
        return text.replace(/<d(\d+)\/>/g, (m, i) => (values[i] !== undefined ? `\u2068${values[i]}\u2069` : ''));
    }
    // Les repères d'une traduction doivent être exactement ceux du texte source
    function sameTags(a, b) {
        const tags = (s) => (s.match(/<\/?[xd]\d+\/?>/g) || []).sort().join('|');
        return tags(a) === tags(b);
    }
    function escapeText(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    function unescapeText(s) { return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&'); }

    function lookup(src) {
        if (!HAS_WORD.test(src.replace(/<\/?[xd]\d+\/?>/g, ''))) return src; // rien à traduire
        if (cache.has(src)) return cache.get(src);
        if (!failed.has(src) && !inflight.has(src)) { pending.add(src); scheduleFlush(); }
        return null;
    }

    // ── Parcours de la page ─────────────────────────────────────────────────

    function noTranslate(el) {
        return el.closest('[translate="no"]') !== null;
    }

    // Un élément est une « phrase » s'il ne contient que du texte et de la mise en forme simple
    // (sans identifiant : l'appli ne s'y réfère pas, on peut donc recréer ces balises).
    function isUnit(el) {
        let hasElement = false;
        for (const n of el.childNodes) {
            if (n.nodeType === 3) continue;
            if (n.nodeType !== 1) continue;
            if (!INLINE.has(n.tagName) || n.id || n.hasAttribute('data-lucide')) return false;
            if (n.getAttribute('translate') !== 'no' && n.children.length) return false;
            hasElement = true;
        }
        return hasElement && HAS_WORD.test(el.textContent);
    }

    function serializeUnit(nodes) {
        let s = '';
        nodes.forEach((n, k) => {
            if (n.nodeType === 3) s += escapeText(n.nodeValue);
            else if (n.nodeType === 1) {
                s += (n.tagName === 'BR' || n.getAttribute('translate') === 'no')
                    ? `<x${k}/>`
                    : `<x${k}>${escapeText(n.textContent)}</x${k}>`;
            }
        });
        return s;
    }

    // Reconstruit les nœuds d'une phrase traduite ; null si les balises ne correspondent pas
    function buildUnit(translated, nodes) {
        const out = [];
        const seen = new Set();
        const re = /<x(\d+)\/>|<x(\d+)>([\s\S]*?)<\/x\2>|<(?!x)|[^<]+/g;
        let m;
        while ((m = re.exec(translated))) {
            if (m[1] !== undefined || m[2] !== undefined) {
                const k = Number(m[1] !== undefined ? m[1] : m[2]);
                const orig = nodes[k];
                if (!orig || orig.nodeType !== 1 || seen.has(k)) return null;
                seen.add(k);
                if (m[1] !== undefined) out.push(orig.cloneNode(true));
                else {
                    const el = orig.cloneNode(false);
                    el.textContent = unescapeText(m[3]);
                    out.push(el);
                }
            } else {
                if (m[0].startsWith('<x') || m[0].startsWith('</x')) return null;
                out.push(document.createTextNode(unescapeText(m[0])));
            }
        }
        const expected = nodes.filter(n => n.nodeType === 1).length;
        return seen.size === expected ? out : null;
    }

    function sameNodes(a, b) {
        if (!a || !b || a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
        return true;
    }

    function handleUnit(el) {
        const current = [...el.childNodes];
        let st = unitState.get(el);
        // L'appli a remplacé le contenu depuis notre passage : c'est le nouveau texte d'origine
        if (!st || (!sameNodes(current, st.applied) && !sameNodes(current, st.nodes))) {
            const raw = serializeUnit(current);
            const lead = raw.match(/^\s*/)[0], trail = raw.match(/\s*$/)[0];
            st = { nodes: current, src: raw.trim(), lead, trail, applied: null };
            unitState.set(el, st);
        }
        if (lang === SOURCE) {
            // Phrase traduite d'un bloc : on remet les nœuds d'origine. Sinon (traduite morceau par
            // morceau, ou pas traduite), on laisse le parcours restaurer chaque texte.
            if (st.applied && sameNodes(current, st.applied)) { el.replaceChildren(...st.nodes); st.applied = null; return true; }
            st.applied = null;
            return false;
        }
        const { src, values } = protect(st.src);
        const tr = lookup(src);
        if (tr === null) return true;   // en attente : le texte d'origine reste affiché
        const built = buildUnit(st.lead + unprotect(tr, values) + st.trail, st.nodes);
        if (!built) return false;       // balises perdues : on traduit morceau par morceau
        el.replaceChildren(...built);
        st.applied = built;
        return true;
    }

    function handleText(node) {
        const value = node.nodeValue;
        let st = textState.get(node);
        if (!st || value !== st.applied) {
            if (!st || value !== st.orig) st = { orig: value, applied: null };
            textState.set(node, st);
        }
        if (lang === SOURCE) {
            if (st.applied !== null && value === st.applied) node.nodeValue = st.orig;
            st.applied = null;
            return;
        }
        const core = st.orig.trim();
        if (!HAS_WORD.test(core.replace(DATA_RE, ''))) return;
        const { src, values } = protect(escapeText(core));
        const tr = lookup(src);
        if (tr === null) return;
        const lead = st.orig.match(/^\s*/)[0], trail = st.orig.match(/\s*$/)[0];
        const text = lead + unescapeText(unprotect(tr, values)) + trail;
        if (node.nodeValue !== text) node.nodeValue = text;
        st.applied = text;
    }

    function handleAttrs(el) {
        let map = attrState.get(el);
        for (const a of ATTRS) {
            if (!el.hasAttribute(a)) continue;
            const value = el.getAttribute(a);
            if (!map) { map = {}; attrState.set(el, map); }
            let st = map[a];
            if (!st || value !== st.applied) { if (!st || value !== st.orig) st = map[a] = { orig: value, applied: null }; }
            if (lang === SOURCE) {
                if (st.applied !== null && value === st.applied) el.setAttribute(a, st.orig);
                st.applied = null;
                continue;
            }
            if (!HAS_WORD.test(st.orig)) continue;
            const { src, values } = protect(escapeText(st.orig.trim()));
            const tr = lookup(src);
            if (tr === null) continue;
            const text = unescapeText(unprotect(tr, values));
            if (value !== text) el.setAttribute(a, text);
            st.applied = text;
        }
    }

    function visit(node) {
        if (node.nodeType === 3) { handleText(node); return; }
        if (node.nodeType !== 1) return;
        const el = node;
        if (el.getAttribute('translate') === 'no') return;
        if (el.namespaceURI === 'http://www.w3.org/2000/svg') {
            if (el.tagName.toLowerCase() === 'svg') handleAttrs(el); // seulement aria-label du dessin
            return;
        }
        if (SKIP_TAGS.has(el.tagName)) { handleAttrs(el); return; }
        handleAttrs(el);
        if (isUnit(el) && handleUnit(el)) return;
        for (const child of [...el.childNodes]) visit(child);
    }

    function handleTitle() {
        const value = document.title;
        if (!titleState || value !== titleState.applied) {
            if (!titleState || value !== titleState.orig) titleState = { orig: value, applied: null };
        }
        if (lang === SOURCE) {
            if (titleState.applied !== null && value === titleState.applied) document.title = titleState.orig;
            titleState.applied = null;
            return;
        }
        const tr = lookup(escapeText(titleState.orig));
        if (tr === null) return;
        document.title = unescapeText(tr);
        titleState.applied = document.title;
    }

    // Applique la langue courante à une partie de la page, sans réagir à nos propres modifications
    function apply(root) {
        if (!root || (root.nodeType === 1 && !root.isConnected)) return;
        if (root.nodeType === 1 && root !== document.body && noTranslate(root)) return;
        visit(root);
        if (observer) observer.takeRecords();
    }
    function applyAll() {
        apply(document.body);
        handleTitle();
        if (observer) observer.takeRecords();
    }

    // ── Textes ajoutés ou modifiés par l'appli ──────────────────────────────

    function onMutations(records) {
        if (lang === SOURCE) return;
        const roots = new Set();
        for (const r of records) {
            let target = r.type === 'characterData' ? r.target.parentElement : r.target;
            if (!target || target.nodeType !== 1) continue;
            // Une phrase déjà traduite d'un bloc : on repart de la phrase entière
            if (!unitState.has(target) && target.parentElement && unitState.has(target.parentElement)) target = target.parentElement;
            roots.add(target);
        }
        for (const el of roots) apply(el);
    }

    function startObserver() {
        if (observer) return;
        observer = new MutationObserver(onMutations);
        observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    }

    // ── Requêtes au relais ──────────────────────────────────────────────────

    function scheduleFlush() {
        if (flushTimer) return;
        flushTimer = setTimeout(flush, 40);
    }

    function setBusy(busy) {
        const btn = document.getElementById('lang-btn');
        if (btn) btn.classList.toggle('animate-pulse', busy);
    }

    function flush() {
        flushTimer = null;
        if (!pending.size || lang === SOURCE || !ENDPOINT) { pending.clear(); return; }
        const all = [...pending];
        pending.clear();
        let batch = [], chars = 0;
        const batches = [];
        for (const s of all) {
            if (batch.length && (batch.length >= BATCH_STRINGS || chars + s.length > BATCH_CHARS)) { batches.push(batch); batch = []; chars = 0; }
            batch.push(s); chars += s.length;
        }
        if (batch.length) batches.push(batch);
        batches.forEach(b => request(b, lang));
    }

    async function request(strings, forLang) {
        strings.forEach(s => inflight.add(s));
        setBusy(true);
        try {
            const resp = await fetch(ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ lang: forLang, strings })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || !Array.isArray(data.translations)) throw new Error(data.error || `HTTP ${resp.status}`);
            if (forLang !== lang) return; // langue changée entre-temps
            strings.forEach((s, i) => {
                const t = data.translations[i];
                if (typeof t === 'string' && t.trim() && sameTags(s, t)) cache.set(s, t);
                else failed.add(s);
            });
            saveCacheSoon();
        } catch (e) {
            console.warn('Traduction indisponible :', e.message);
            strings.forEach(s => failed.add(s));
            // Nouvel essai possible dans une minute (relais saturé, réseau coupé…)
            setTimeout(() => { strings.forEach(s => failed.delete(s)); if (lang === forLang) queueRender(); }, 60000);
        } finally {
            strings.forEach(s => inflight.delete(s));
            setBusy(inflight.size > 0);
            if (forLang === lang) queueRender();
        }
    }

    function queueRender() {
        if (renderQueued) return;
        renderQueued = true;
        requestAnimationFrame(() => { renderQueued = false; applyAll(); });
    }

    // ── Choix de la langue ──────────────────────────────────────────────────

    function setLang(code, { remember = true } = {}) {
        if (!SUPPORTED.has(code)) code = SOURCE;
        if (remember) { try { localStorage.setItem(STORE_KEY, code); } catch (e) {} }
        if (code === lang) return;
        lang = code;
        cache = code === SOURCE ? new Map() : loadCache(code);
        pending.clear();
        failed.clear();
        document.documentElement.lang = code;
        startObserver();
        applyAll();
        renderMenu();
    }

    function initialLang() {
        let saved = null;
        try { saved = localStorage.getItem(STORE_KEY); } catch (e) {}
        if (saved && SUPPORTED.has(saved)) return saved;
        // Première visite : langue du navigateur si elle est proposée (pas pour les robots d'indexation)
        if (navigator.webdriver || /bot|crawl|spider|slurp|lighthouse/i.test(navigator.userAgent)) return SOURCE;
        for (const l of navigator.languages || [navigator.language]) {
            const base = String(l || '').toLowerCase().split('-')[0];
            const code = base === 'no' || base === 'nn' ? 'nb' : base;
            if (SUPPORTED.has(code)) return code;
        }
        return SOURCE;
    }

    // ── Menu des langues ────────────────────────────────────────────────────

    function renderMenu() {
        const list = document.getElementById('lang-list');
        const current = document.getElementById('lang-current');
        if (current) current.textContent = lang.toUpperCase();
        if (!list) return;
        list.replaceChildren();
        for (const [code, name] of LANGS) {
            const li = document.createElement('li');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.setAttribute('role', 'option');
            btn.setAttribute('aria-selected', String(code === lang));
            btn.lang = code;
            btn.dataset.lang = code;
            btn.textContent = name;
            btn.className = 'w-full text-left px-3 py-2 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 '
                + (code === lang ? 'bg-slate-900 text-white font-medium' : 'text-slate-700 hover:bg-slate-100');
            btn.addEventListener('click', () => { setLang(code); closeMenu(true); });
            li.appendChild(btn);
            list.appendChild(li);
        }
    }

    function openMenu() {
        const menu = document.getElementById('lang-menu');
        const btn = document.getElementById('lang-btn');
        menu.classList.remove('hidden');
        btn.setAttribute('aria-expanded', 'true');
        const sel = menu.querySelector('[aria-selected="true"]');
        if (sel) { sel.scrollIntoView({ block: 'nearest' }); sel.focus({ preventScroll: true }); }
    }
    function closeMenu(focusButton = false) {
        const menu = document.getElementById('lang-menu');
        const btn = document.getElementById('lang-btn');
        if (!menu || menu.classList.contains('hidden')) return;
        menu.classList.add('hidden');
        btn.setAttribute('aria-expanded', 'false');
        if (focusButton) btn.focus();
    }

    function initMenu() {
        const btn = document.getElementById('lang-btn');
        const menu = document.getElementById('lang-menu');
        if (!btn || !menu) return;
        renderMenu();
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.contains('hidden') ? openMenu() : closeMenu();
        });
        document.addEventListener('click', (e) => { if (!menu.contains(e.target)) closeMenu(); });
        document.addEventListener('keydown', (e) => {
            if (menu.classList.contains('hidden')) return;
            if (e.key === 'Escape') { closeMenu(true); return; }
            if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
            const items = [...menu.querySelectorAll('button[data-lang]')];
            const i = items.indexOf(document.activeElement);
            const next = items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length];
            if (next) { e.preventDefault(); next.focus(); }
        });
    }

    // ── Démarrage ───────────────────────────────────────────────────────────

    initMenu();
    const start = initialLang();
    if (start !== SOURCE) setLang(start, { remember: false });

    window.Traduction = { setLang, get lang() { return lang; }, languages: LANGS.slice() };
})();
