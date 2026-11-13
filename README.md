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
