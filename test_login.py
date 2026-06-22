"""
Test-Skript: Schritt 1 - schauen, ob Login + Auslesen ueberhaupt klappt.

Nutzung (in der PowerShell, im Projektordner):

    py test_login.py                 # nur Login testen + Termine suchen
    py test_login.py --event-id 1234 # zusaetzlich ein Training auslesen

Zugangsdaten kommen aus der Datei .env (siehe .env.example).
Roh-HTML wird in den Ordner _debug/ gespeichert, damit wir die Struktur
anschauen und das Parsen verfeinern koennen.
"""

import argparse
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

from spielerplus import BASE, SpielerPlus, SpielerPlusError

DEBUG_DIR = Path(__file__).parent / "_debug"


def load_env() -> dict:
    """Sehr einfacher .env-Leser (KEY=VALUE pro Zeile)."""
    env = {}
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def save_debug(name: str, html: str) -> Path:
    DEBUG_DIR.mkdir(exist_ok=True)
    p = DEBUG_DIR / name
    p.write_text(html, encoding="utf-8")
    return p


def find_event_links(html: str) -> list[str]:
    """Alle Links zu Terminen/Events auf einer Seite einsammeln."""
    soup = BeautifulSoup(html, "html.parser")
    ids = set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"/event/view\?id=(\d+)", a["href"])
        if m:
            ids.add(int(m.group(1)))
    return sorted(ids)


def parse_participation(html: str) -> dict:
    """
    Best-effort: Teilnehmer nach Status gruppieren.
    SpielerPlus gruppiert die Mitglieder typischerweise in Bloecke
    (Zugesagt / Unsicher / Abgesagt). Wir suchen Ueberschriften und die
    danach folgenden Namen. Klappt das nicht sauber, hilft das Roh-HTML
    im Ordner _debug/.
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {"zugesagt": [], "unsicher": [], "abgesagt": [], "roh_text": ""}

    text = soup.get_text("\n", strip=True)
    result["roh_text"] = text

    # Namen stehen meist in Elementen mit "participant"/"member" im class-Namen.
    name_nodes = soup.select(
        "[class*=participant] [class*=name], [class*=member] [class*=name], "
        "[class*=participation] [class*=name]"
    )
    names = [n.get_text(strip=True) for n in name_nodes if n.get_text(strip=True)]
    result["alle_namen"] = sorted(set(names))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event-id", type=int, default=None)
    args = ap.parse_args()

    env = load_env()
    email = env.get("SP_EMAIL") or os.environ.get("SP_EMAIL")
    pw = env.get("SP_PASSWORD") or os.environ.get("SP_PASSWORD")
    if not email or not pw:
        print("FEHLER: SP_EMAIL / SP_PASSWORD fehlen. Lege eine .env an "
              "(siehe .env.example).")
        return

    sp = SpielerPlus(email, pw)
    print(f"-> Login als {email} ...")
    try:
        sp.login()
    except SpielerPlusError as e:
        print(f"FEHLER beim Login: {e}")
        return
    print("OK: Login erfolgreich.\n")

    # Startseite/Dashboard laden und nach Terminen suchen.
    print("-> Lade Startseite und suche Termine ...")
    home = sp.get("/").text
    save_debug("home.html", home)
    ids = find_event_links(home)

    # Falls auf der Startseite nichts steht, Termin-Uebersicht probieren.
    if not ids:
        for path in ("/event", "/event/index", "/dashboard"):
            try:
                html = sp.get(path).text
                save_debug(f"page_{path.strip('/').replace('/', '_')}.html", html)
                ids = find_event_links(html)
                if ids:
                    break
            except Exception:
                pass

    if ids:
        print(f"OK: {len(ids)} Termin(e) gefunden. Beispiel-IDs: {ids[:10]}")
    else:
        print("Keine Termin-Links automatisch gefunden. "
              "Schau in _debug/home.html, wie die Links aussehen.")

    print("\nLogin-Test fertig. Fuer Trainings + Zu-/Absagen nutze jetzt:")
    print("    py show_training.py")


if __name__ == "__main__":
    main()
