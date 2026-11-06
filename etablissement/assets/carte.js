// Carte OSM : géocodage à l'affichage via l'API de la Géoplateforme (IGN / BAN).
// Adresse complète -> point précis ; sinon (ou si l'adresse n'est pas trouvée) -> centre de la commune.
(function () {
  var el = document.getElementById("carte");
  var note = document.getElementById("carte-note");
  if (!el) return;
  if (!window.L) { el.style.display = "none"; note.textContent = "Carte indisponible."; return; }
  var adr = el.dataset.adresse, cp = el.dataset.cp, ville = el.dataset.ville;
  var API = "https://data.geopf.fr/geocodage/search";

  function cherche(params) {
    var u = API + "?" + new URLSearchParams(Object.assign({ limit: 1 }, params));
    return fetch(u).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { return j && j.features && j.features[0]; })
      .catch(function () { return null; });
  }

  function affiche(f, precis) {
    var c = f.geometry.coordinates; // [lon, lat]
    var map = L.map(el, { scrollWheelZoom: false }).setView([c[1], c[0]], precis ? 16 : 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© contributeurs OpenStreetMap"
    }).addTo(map);
    if (precis) {
      L.marker([c[1], c[0]]).addTo(map);
      note.textContent = "Position d’après l’adresse déclarée.";
    } else {
      L.circle([c[1], c[0]], { radius: 1200, color: "#5A3E9E", weight: 2, fillOpacity: .12 }).addTo(map);
      note.textContent = "Adresse incomplète : la carte montre la commune, l’usine se trouve dans ce secteur.";
    }
  }

  var etape1 = adr
    ? cherche({ q: adr + " " + ville, postcode: cp }).then(function (f) {
        return f && f.properties.score >= 0.45 && f.properties.type !== "municipality" ? f : null;
      })
    : Promise.resolve(null);

  etape1.then(function (f) {
    if (f) return affiche(f, true);
    return cherche({ q: ville, postcode: cp, type: "municipality" })
      .then(function (g) { return g || cherche({ q: ville + " " + cp, type: "municipality" }); })
      .then(function (g) {
        if (g) affiche(g, false);
        else { el.style.display = "none"; note.textContent = "Localisation impossible pour cette adresse."; }
      });
  });
})();
