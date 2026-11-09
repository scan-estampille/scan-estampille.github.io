# Estampille Sanitaire CE

Application web gratuite pour identifier l'établissement qui a fabriqué ou conditionné un produit alimentaire, à partir du numéro inscrit dans l'ovale sanitaire de l'emballage (par exemple « FR 49.099.002 CE »).

**Site : https://scan-estampille.github.io**

On peut saisir le numéro, le nom d'une entreprise ou une commune, ou photographier l'estampille. L'application recherche le numéro dans la liste officielle des établissements agréés publiée par la DGAL (ministère de l'Agriculture) et affiche l'établissement, son adresse, ses activités et les espèces travaillées. Elle s'installe sur mobile et la recherche fonctionne hors connexion.

## Fonctionnement

- **Site statique** hébergé sur GitHub Pages : aucun serveur, aucune base de données, aucun compte utilisateur.
- **Liste officielle** : le fichier `ETAB_AGR_853.txt` de la DGAL, mis à jour chaque jour dans le dépôt et conservé dans le navigateur (IndexedDB) pour la recherche hors ligne.
- **Relais Cloudflare** (un worker, hors de ce dépôt) pour trois usages :
  - `GET /dgal` : relais de la liste officielle, que le Ministère publie sans en-têtes CORS ;
  - `POST /` : lecture des photos. Le relais repère chaque estampille ovale, lit son numéro et renvoie sa position ; une photo contenant plusieurs estampilles est relue de près ovale par ovale. Services utilisés, dans l'ordre : Groq, puis Cloudflare Workers AI si Groq est saturé, lent ou en échec ;
  - `POST /contact` : messages à l'auteur, avec photos jointes, transmis par e-mail via Resend.
- **Règle de lecture** : un numéro n'est jamais deviné. Un numéro absent de la liste ou partiellement lu donne des suggestions que l'utilisateur choisit lui-même.

Les clés des services et l'adresse de l'auteur ne sont jamais dans ce dépôt ni dans le navigateur : elles sont stockées dans les secrets du worker.

## Organisation du dépôt

| Chemin | Rôle |
|---|---|
| `index.html` | L'application complète (HTML, CSS de mise en page, JavaScript) |
| `sw.js` | Service worker : fonctionnement hors ligne et mise en cache |
| `manifest.webmanifest`, `icons/` | Installation sur mobile (PWA) et icônes |
| `assets/tailwind.css` | CSS compilé (ne pas modifier à la main) |
| `assets/lucide-1.59.0.min.js` | Icônes Lucide |
| `src/tailwind.css`, `tailwind.config.js`, `package.json` | Sources et configuration de Tailwind CSS |
| `ETAB_AGR_853.txt` | Copie de la liste officielle DGAL |
| `.github/workflows/maj-liste-dgal.yml` | Mise à jour quotidienne de la liste |
| `etablissement/` | Pages statiques d'établissements, pour le référencement |
| `sitemap.xml`, `robots.txt` | Référencement |
| `google…html` | Vérification Google Search Console |

Les pages de `etablissement/` et le `sitemap.xml` sont générés hors de ce dépôt et ne se mettent pas à jour avec la liste : à régénérer de temps en temps.

## Mise à jour de la liste officielle

Le workflow `maj-liste-dgal.yml` s'exécute chaque jour à 4 h 17 UTC. Il télécharge la liste sur le site de la DGAL, ou par le relais Cloudflare en secours, et ne la publie que si elle passe deux contrôles :

- au moins 1 000 établissements ;
- pas plus de 20 % de lignes perdues par rapport à la version précédente.

Un commit n'est créé que si la liste a changé.

Pour le lancer à la main : onglet *Actions*, *Mise à jour de la liste DGAL*, puis *Run workflow*. Il doit pouvoir écrire dans le dépôt : *Settings › Actions › General › Workflow permissions* sur *Read and write permissions*.

## Configuration du worker Cloudflare

À créer dans *Workers & Pages › estampille-ocr › Settings*.

| Nom | Type | Rôle |
|---|---|---|
| `ALLOWED_ORIGINS` | Variable | `https://scan-estampille.github.io` |
| `GROQ_API_KEY` | Secret | Clé API Groq |
| `GROQ_VISION_MODEL` | Variable | Modèle de vision Groq, par exemple `qwen/qwen3.8-27b` |
| `AI` | Binding Workers AI | Lecture de secours, gratuite |
| `RESEND_API_KEY` | Secret | Clé API Resend, permission *Sending access* |
| `CONTACT_TO` | Secret | Adresse qui reçoit les messages (celle du compte Resend) |
| `RATE_LIMITER` | Binding (facultatif) | Limite de requêtes par adresse IP |
| `OCR_PROVIDERS` | Variable (facultatif) | Ordre des services, par défaut `groq,workersai` |
| `WORKERS_AI_MODEL` | Variable (facultatif) | Modèle Workers AI, par défaut `@cf/meta/llama-4-scout-17b-16e-instruct` |
| `OCR_HEDGE_MS` | Variable (facultatif) | Délai en ms avant de lancer le service suivant en parallèle, par défaut `4000` |

Les journaux du worker (*Logs*) indiquent, pour chaque lecture, les services essayés, leur durée et leur réponse brute.

## Maintenance

**Recompiler le CSS** après avoir modifié des classes dans `index.html` :

```bash
npm install
npm run build:css
```

Le projet utilise **Tailwind CSS v3** : les noms de classes propres à la v4 (`shadow-xs`, `outline-hidden`, `backdrop-blur-xs`…) n'ont aucun effet. Ne jamais remplacer `src/tailwind.css` par le CSS compilé : il ne contient que les trois directives `@tailwind`.

**À chaque mise en ligne** :

- incrémenter `VERSION` dans `sw.js`, pour que les utilisateurs reçoivent les nouveaux fichiers ;
- changer `APP_VERSION` dans `index.html`, qui est indiquée dans les signalements d'erreur.

## Confidentialité

- **Recherches** : effectuées dans le navigateur, rien n'est envoyé.
- **Photos** : réduites sur l'appareil, envoyées par le relais à Groq, ou à Cloudflare Workers AI en secours, pour lire le numéro, puis oubliées. L'application ne les enregistre pas.
- **Messages à l'auteur** : message, adresse e-mail facultative, photos jointes et détails techniques passent par le relais et Resend, puis arrivent par e-mail chez l'auteur.
- **Mesure d'audience** : Cloudflare Web Analytics, sans cookie.

## Contact

Depuis l'application : *À propos › Contacter l'auteur*. Après une photo mal lue, le bouton « Envoyer la photo à l'auteur » joint directement la photo et les détails techniques.
