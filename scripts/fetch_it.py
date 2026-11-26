#!/usr/bin/env python3
"""Télécharge la page de la liste officielle italienne (Reg. CE 853/2004) avec un vrai navigateur.

Le site du ministère italien est protégé par Gcore : un programme qui télécharge la page
directement reçoit une « Browser Validation Page » qui exige JavaScript et cookies. Ce script
ouvre donc la page dans Chromium sans écran (Playwright), laisse passer la vérification
comme le ferait un navigateur ordinaire, puis enregistre le code de la page obtenue.

La liste fait plusieurs millions de caractères et le serveur l'envoie lentement : la page
n'est enregistrée qu'une fois entièrement chargée (document.readyState == "complete" et
taille stable entre deux relevés), pour ne jamais enregistrer un tableau tronqué.

Il ne fait jamais échouer le workflow : si la vérification n'est pas franchie ou si la page
n'a pas fini de se charger à temps, il affiche un avertissement, n'écrit pas de fichier, et
la liste italienne actuelle est conservée.
En cas d'échec, une capture et le code de la page reçue sont enregistrés dans debug/.

Usage :
  pip install playwright && python -m playwright install --with-deps chromium
  python scripts/fetch_it.py --out italie.html
"""
import argparse, os, re, sys, time
from playwright.sync_api import sync_playwright

URL = ("https://www.salute.gov.it/consultazioneStabilimenti/"
       "ConsultazioneStabilimentiServlet?ACTION=gestioneSingolaCategoria&idNormativa=2")
# Navigateur ordinaire : la protection refuse plus facilement le « HeadlessChrome » des navigateurs automatiques
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
MIN_CHARS = 200_000         # la vraie liste fait plusieurs millions de caractères
WAIT_SECONDS = 300          # vérification + génération de la liste (le serveur met ~30 s à répondre)
POLL_MS = 5_000


def is_gate(html):
    """Page de vérification de Gcore (« Browser Validation Page »)."""
    return "Browser Validation Page" in html or re.search(r"<title>\s*Gcore\s*</title>", html, re.I) is not None


def has_list(html):
    return len(html) >= MIN_CHARS and not is_gate(html)


def excerpt(html, size=300):
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:size]


def save_debug(page, html):
    os.makedirs("debug", exist_ok=True)
    try:
        page.screenshot(path="debug/italie.png", full_page=False)
    except Exception as e:
        print(f"Capture impossible : {e}", file=sys.stderr)
    with open("debug/italie.html", "w", encoding="utf-8") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="italie.html")
    args = ap.parse_args()

    html = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=USER_AGENT, locale="it-IT",
                                      viewport={"width": 1366, "height": 900})
        page = context.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=WAIT_SECONDS * 1000)
        except Exception as e:  # la page de vérification redirige : on regarde quand même ce qui est affiché
            print(f"Chargement initial : {e}", file=sys.stderr)

        deadline = time.time() + WAIT_SECONDS
        seen_gate = False
        complete = False
        last_len = -1
        while time.time() < deadline:
            try:
                html = page.content()
                ready = page.evaluate("document.readyState") == "complete"
            except Exception:
                html, ready = "", False   # redirection en cours après la vérification
            if has_list(html) and ready:
                if len(html) == last_len:   # taille stable sur deux relevés : chargement terminé
                    complete = True
                    break
                last_len = len(html)
            else:
                last_len = -1
            if is_gate(html) and not seen_gate:
                seen_gate = True
                print("Page de vérification Gcore : attente de la redirection…")
            page.wait_for_timeout(POLL_MS)

        if not complete:
            save_debug(page, html)
        browser.close()

    if complete:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Liste reçue ({len(html)} caractères){' après la vérification Gcore' if seen_gate else ''}.")
        return

    if is_gate(html):
        reason = "la page de vérification Gcore n'a pas été franchie (navigateur automatique refusé)"
    elif has_list(html):
        reason = f"chargement de la liste non terminé après {WAIT_SECONDS} s ({len(html)} caractères reçus)"
    else:
        reason = f"page inattendue de {len(html)} caractères"
    print(f"Extrait de la page reçue : {excerpt(html)}", file=sys.stderr)
    print(f"::warning title=Liste italienne non mise à jour::{reason}. La liste actuelle est conservée. "
          "Mise à jour manuelle : ouvrir la page dans un navigateur, « Enregistrer sous » "
          "(HTML uniquement) et déposer le fichier dans le dépôt sous sources/italie.html.")


if __name__ == "__main__":
    main()
