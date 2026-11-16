#!/usr/bin/env python3
"""Télécharge l'export CSV de la Generalliste allemande (BLtU) sur le site du BVL.

Le site n'a pas d'adresse de téléchargement fixe : chaque visite ouvre une session et les liens
changent (execution=e1s7, e4s1…). Ce script fait donc comme une personne : il ouvre le site dans
un navigateur sans écran (Playwright), affiche la Generalliste et clique sur « Export als CSV ».

En cas d'échec, une capture d'écran et le code de la page sont enregistrés dans debug/ :
le workflow GitHub les joint au rapport d'exécution pour comprendre ce qui a changé.

Usage :
  pip install playwright && python -m playwright install --with-deps chromium
  python scripts/fetch_de.py --out generalliste.csv
"""
import argparse, os, re, sys
from playwright.sync_api import sync_playwright

START_URL = "https://bltu.bvl.bund.de/bltu/"
TIMEOUT_MS = 120_000
DOWNLOAD_TIMEOUT_MS = 600_000   # l'export de ~16 000 lignes peut être long à préparer


def save_debug(page, name):
    os.makedirs("debug", exist_ok=True)
    try:
        page.screenshot(path=f"debug/{name}.png", full_page=True)
        with open(f"debug/{name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception as e:  # le débogage ne doit pas masquer l'erreur d'origine
        print(f"Capture impossible : {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="generalliste.csv")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(accept_downloads=True, locale="de-DE",
                                      viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        step = "accueil"
        try:
            page.goto(START_URL, wait_until="networkidle")

            # 1. Page d'accueil → Generalliste (liste de tous les établissements)
            step = "generalliste"
            if not page.get_by_text("Export als").count():
                page.get_by_text(re.compile("Generalliste", re.I)).first.click()
                page.wait_for_load_state("networkidle")

            # 2. Bouton « CSV » en bas du tableau (identifiant se terminant par « export1 »)
            step = "export"
            page.get_by_text("Export als").first.wait_for()
            button = page.locator("[id$='export1']")
            if not button.count():
                button = page.get_by_text("CSV", exact=True)
            with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
                button.first.click()
            download = info.value
            download.save_as(args.out)
        except Exception as e:
            save_debug(page, step)
            sys.exit(f"Échec à l'étape « {step} » : {e}")
        finally:
            browser.close()

    size = os.path.getsize(args.out)
    print(f"Export enregistré : {args.out} ({size:,} octets)")
    if size < 500_000:
        sys.exit("Fichier trop petit : l'export n'est probablement pas la liste complète.")


if __name__ == "__main__":
    main()
