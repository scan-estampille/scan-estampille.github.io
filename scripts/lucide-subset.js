// Sous-ensemble de lucide : seules les icônes utilisées par l'appli (≈ 6 Ko au lieu de 454 Ko).
// Régénérer : npm install && npm run build:icons
// Ajouter une icône : l'importer et l'ajouter à « icons » ci-dessous, avec son nom en PascalCase
// (data-lucide="map-pin" → MapPin ; les anciens noms comme loader-2 ou alert-triangle restent valables).
import { createIcons as create, AlertTriangle, Building2, Camera, CheckCircle2, ExternalLink, Heart, HeartHandshake,
  Image, Info, Loader2, Mail, MapPin, Navigation, Paperclip, Satellite, ScanLine, Search, Send, X } from 'lucide';

const icons = { AlertTriangle, Building2, Camera, CheckCircle2, ExternalLink, Heart, HeartHandshake,
  Image, Info, Loader2, Mail, MapPin, Navigation, Paperclip, Satellite, ScanLine, Search, Send, X };

// Même interface que le fichier complet : window.lucide.createIcons()
window.lucide = {
  icons,
  createIcons: (opts = {}) => create({ ...opts, icons: { ...icons, ...(opts.icons || {}) } }),
};
