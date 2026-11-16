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
PROCESS_URL = "https://bltu.bvl.bund.de/bltu/app/process/bvl-btl_p_veroeffentlichung"
# Paramètres des liens observés sur le site (les « . » et « - » des identifiants y sont codés _002e et _002d) :
# bouton « Generalliste » de l'accueil, puis lien « CSV » sous le tableau
GENERALLISTE_PARAM = "osForm%3Aid_002eqsj=clicked"
EXPORT_PARAM = ("osForm%3Abvl_002dbtl_002ep__veroeffentlichung_002egeneralliste__part_002edGrid%3A50%3A"
                "bvl_002dbtl_002ep__veroeffentlichung_002egeneralliste__part_002edGrid_002eexport1=clicked")
# Navigateur ordinaire : certains sites refusent le « HeadlessChrome » des navigateurs automatiques
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
STEP_TIMEOUT_MS = 15_000
TIMEOUT_MS = 120_000
DOWNLOAD_TIMEOUT_MS = 600_000   # l'export de ~16 000 lignes peut être long à préparer


def save_debug(page, name):
    """Capture, code de la page et liste des éléments cliquables, pour comprendre un échec."""
    os.makedirs("debug", exist_ok=True)
    try:
        page.screenshot(path=f"debug/{name}.png", full_page=True)
        with open(f"debug/{name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        items = page.eval_on_selector_all(
            "a, button, input[type=submit], input[type=button], [onclick]",
            "els => els.map(e => `${e.tagName} id=${e.id || '-'} | ${(e.innerText || e.value || '').trim().slice(0, 80)}`)")
        with open(f"debug/{name}-cliquables.txt", "w", encoding="utf-8") as f:
            f.write(f"URL : {page.url}\nTitre : {page.title()}\n\n" + "\n".join(items))
        print(f"URL au moment de l'échec : {page.url}", file=sys.stderr)
    except Exception as e:  # le débogage ne doit pas masquer l'erreur d'origine
        print(f"Capture impossible : {e}", file=sys.stderr)


def execution_of(page):
    """Étape courante de la session (« e1s2 »), lue dans l'adresse de la page."""
    m = re.search(r"execution=(e\d+s\d+)", page.url)
    return m.group(1) if m else None


def action_url(execution, param):
    return f"{PROCESS_URL}?execution={execution}&osForm=osForm&javax.faces.ViewState={execution}&{param}"


def pass_gate(page):
    """Page « In Ihrem Browser ist derzeit JavaScript nicht aktiviert » : on clique sur son bouton."""
    for _ in range(3):
        if not page.get_by_text(re.compile(r"JavaScript.{0,40}nicht aktiviert", re.I)).count():
            return
        button = page.locator("input[type=submit], input[type=button], button, a[href]").filter(visible=True)
        if not button.count():
            raise RuntimeError("page « JavaScript nicht aktiviert » sans bouton")
        print(f"Page d'entrée : clic sur « {(button.first.inner_text() or button.first.get_attribute('value') or '').strip()[:60]} »")
        button.first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)


def export_visible(page, timeout=STEP_TIMEOUT_MS):
    try:
        page.get_by_text("Export als").first.wait_for(timeout=timeout)
        return True
    except Exception:
        return False


def open_generalliste(page):
    """Accueil → Generalliste : bouton « Generalliste », sinon le lien observé sur le site."""
    if export_visible(page, 3000):
        return
    link = page.get_by_text(re.compile(r"^\s*Generalliste\s*$", re.I))
    if link.count():
        print("Clic sur « Generalliste »")
        link.first.click()
        page.wait_for_load_state("networkidle")
        if export_visible(page):
            return
    ex = execution_of(page)
    if ex:
        print(f"Lien direct vers la Generalliste (étape {ex})")
        page.goto(action_url(ex, GENERALLISTE_PARAM), wait_until="networkidle")
        if export_visible(page):
            return
    raise RuntimeError("Generalliste introuvable (voir debug/)")


def download_csv(page, out):
    """Lien « CSV » sous le tableau ; à défaut, le lien observé sur le site, avec la même session."""
    button = page.locator("[id$='export1']")
    if not button.count():
        button = page.get_by_text("CSV", exact=True)
    if button.count():
        try:
            with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
                button.first.click()
            info.value.save_as(out)
            return
        except Exception as e:
            print(f"Clic sur « CSV » sans téléchargement : {e}", file=sys.stderr)
    ex = execution_of(page)
    if not ex:
        raise RuntimeError("étape de session introuvable pour l'export")
    print(f"Lien direct vers l'export CSV (étape {ex})")
    resp = page.context.request.get(action_url(ex, EXPORT_PARAM), timeout=DOWNLOAD_TIMEOUT_MS)
    body = resp.body()
    if not resp.ok or body[:200].lstrip().lower().startswith(b"<!doctype") or b"<html" in body[:500].lower():
        raise RuntimeError(f"l'export a renvoyé une page web au lieu du fichier (HTTP {resp.status})")
    with open(out, "wb") as f:
        f.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="generalliste.csv")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(accept_downloads=True, locale="de-DE", user_agent=USER_AGENT,
                                      viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        step = "accueil"
        try:
            page.goto(START_URL, wait_until="networkidle")
            page.wait_for_timeout(2000)

            step = "entree"          # page « JavaScript nicht aktiviert » et son bouton
            pass_gate(page)

            step = "generalliste"    # liste de tous les établissements
            open_generalliste(page)

            step = "export"          # « Export als CSV », en bas à gauche du tableau
            download_csv(page, args.out)
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
