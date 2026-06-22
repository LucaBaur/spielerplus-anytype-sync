"""
SpielerPlus-Client (inoffiziell, Web-Scraping).

SpielerPlus hat KEINE offizielle API. Dieser Client meldet sich mit
E-Mail + Passwort an (wie ein Browser) und liest danach die HTML-Seiten aus.

Der Login ist bewusst robust gebaut: Wir laden die Login-Seite, lesen das
echte <form> samt CSRF-Token aus und schicken die Zugangsdaten an die
Formular-Action zurueck. So muessen wir keine Feldnamen hart kodieren, die
sich jederzeit aendern koennen.
"""

import re
import sys

import requests
from bs4 import BeautifulSoup

BASE = "https://www.spielerplus.de"
LOGIN_URL = f"{BASE}/site/login"

# Browser-aehnliche Header, damit wir nicht sofort geblockt werden.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


class SpielerPlusError(Exception):
    pass


class SpielerPlus:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ------------------------------------------------------------------ login
    def login(self) -> None:
        # 1) Login-Seite laden, um Formular + CSRF-Token zu bekommen.
        r = self.session.get(LOGIN_URL, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        form = self._find_login_form(soup)
        if form is None:
            raise SpielerPlusError(
                "Login-Formular nicht gefunden. Eventuell hat SpielerPlus "
                "die Seite geaendert oder es gibt eine Sperre."
            )

        action = form.get("action") or "/site/login"
        post_url = action if action.startswith("http") else BASE + action

        # 2) Alle Felder des Formulars uebernehmen (inkl. verstecktem _csrf).
        data = {}
        for inp in form.find_all(("input", "textarea")):
            name = inp.get("name")
            if not name:
                continue
            data[name] = inp.get("value", "")

        # 3) E-Mail- und Passwortfeld automatisch erkennen und fuellen.
        email_field = self._guess_field(form, ("email", "username", "login"))
        pass_field = self._guess_field(form, ("password", "pass"))
        if not email_field or not pass_field:
            raise SpielerPlusError(
                f"E-Mail-/Passwortfeld nicht erkannt. Gefundene Felder: "
                f"{list(data.keys())}"
            )
        data[email_field] = self.email
        data[pass_field] = self.password

        # "Angemeldet bleiben" mitschicken, falls vorhanden.
        for name in list(data.keys()):
            if "remember" in name.lower():
                data[name] = "1"

        # 4) Login absenden.
        r2 = self.session.post(
            post_url, data=data, headers={"Referer": LOGIN_URL}, timeout=30
        )
        r2.raise_for_status()

        # Hat der Server eine Fehlermeldung ins Formular geschrieben?
        err = self._form_error(r2.text)
        if err:
            raise SpielerPlusError(f"Login abgelehnt: {err}")

        # Gegenprobe: geschuetzte Seite aufrufen. Werden wir zum Login
        # umgeleitet, hat die Anmeldung nicht funktioniert.
        check = self.session.get(
            BASE + "/dashboard", timeout=30, allow_redirects=True
        )
        if "/site/login" in check.url:
            raise SpielerPlusError(
                "Login fehlgeschlagen (keine Session). Stimmen E-Mail/Passwort?"
            )

    # --------------------------------------------------------------- requests
    def get(self, path: str) -> requests.Response:
        url = path if path.startswith("http") else BASE + path
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r

    # ----------------------------------------------------------------- teams
    def list_teams(self) -> list[dict]:
        """Alle Teams/Mitgliedschaften des Accounts (Name + switch-id)."""
        html = self.get("/site/select-team").text
        soup = BeautifulSoup(html, "html.parser")
        teams = []
        seen = set()
        for item in soup.select(".select-team-item"):
            a = item.find("a", href=re.compile(r"/site/switch-user\?id=\d+"))
            name_el = item.select_one(".select-team-item-meta h4")
            if not a or not name_el:
                continue
            team_id = int(re.search(r"id=(\d+)", a["href"]).group(1))
            if team_id in seen:
                continue
            seen.add(team_id)
            teams.append({"id": team_id, "name": name_el.get_text(strip=True)})
        return teams

    def switch_team(self, team_id: int) -> None:
        """Aktives Team wechseln (jede Mitgliedschaft hat eine eigene id)."""
        self.get(f"/site/switch-user?id={team_id}")

    # ---------------------------------------------------------------- events
    def list_events(self) -> list[dict]:
        """Kommende Termine des aktiven Teams (Typ, id, Wochentag, Tag, Titel)."""
        html = self.get("/events/index").text
        soup = BeautifulSoup(html, "html.parser")
        events = []
        for panel in soup.select('[id^="event-"]'):
            m = re.match(r"event-([a-z]+)-(\d+)", panel.get("id", ""))
            if not m:
                continue
            etype, eid = m.group(1), int(m.group(2))
            head_info = panel.select_one(".panel-heading-info")
            head_text = panel.select_one(".panel-heading-text")
            weekday = day = title = ""
            if head_info:
                t = head_info.select_one(".panel-title")
                s = head_info.select_one(".panel-subtitle")
                weekday = t.get_text(strip=True) if t else ""
                day = s.get_text(strip=True) if s else ""
            if head_text:
                tt = head_text.select_one(".panel-title")
                title = tt.get_text(strip=True) if tt else ""
            events.append(
                {"type": etype, "id": eid, "weekday": weekday,
                 "day": day, "title": title}
            )
        return events

    def get_participation(self, event_type: str, event_id: int) -> dict:
        """Teilnehmerliste eines Termins per AJAX holen und strukturieren.

        Liefert: {"title", "datetime", "groups": {
            "zugesagt": [{"name", "user_id"}], "abgesagt": [...],
            "unsicher": [...], "offen": [...]}}
        """
        # CSRF-Token mitschicken, falls vorhanden (Yii). Session-Cookie reicht
        # meist schon, aber sicher ist sicher.
        csrf = self._csrf_token()
        headers = {"X-Requested-With": "XMLHttpRequest",
                   "Referer": f"{BASE}/events/index"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        data = {"eventid": event_id, "eventtype": event_type}
        if csrf:
            data["_csrf"] = csrf
        r = self.session.post(
            f"{BASE}/events/ajaxgetparticipation", data=data,
            headers=headers, timeout=30,
        )
        r.raise_for_status()
        try:
            inner = r.json().get("html", "")
        except ValueError:
            inner = r.text
        return self._parse_participation(inner)

    def _csrf_token(self) -> str | None:
        cookie = self.session.cookies.get("_csrf")
        # Token kommt aus dem <meta>-Tag einer Seite, nicht aus dem Cookie.
        html = self.get("/events/index").text
        m = re.search(r'name="csrf-token" content="([^"]+)"', html)
        return m.group(1) if m else None

    # ----------------------------------------------------------------- parser
    GROUP_KEYS = ("zugesagt", "abgesagt", "unsicher", "offen", "nicht_nominiert")

    @staticmethod
    def _status_key(label: str) -> str | None:
        """Ordnet die Sektions-Ueberschrift einem internen Schluessel zu.
        SpielerPlus nennt die Absage-Sektion 'Absagen / Abwesend'."""
        low = label.lower()
        if "zugesagt" in low:
            return "zugesagt"
        if "unsicher" in low:
            return "unsicher"
        if "absage" in low or "abwesend" in low:
            return "abgesagt"
        if "nicht nominiert" in low:
            return "nicht_nominiert"
        if "noch nicht" in low:
            return "offen"
        return None

    @classmethod
    def _parse_participation(cls, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        header = soup.select_one(".participation-header .headline_small")
        subline = soup.select_one(".participation-header .subline")
        result = {
            "title": header.get_text(strip=True) if header else "",
            "datetime": subline.get_text(strip=True) if subline else "",
            "groups": {k: [] for k in cls.GROUP_KEYS},
        }
        for block in soup.select(".participation-list"):
            head = block.select_one(".participation-list-header")
            if not head:
                continue
            label = head.get_text(" ", strip=True)
            key = cls._status_key(label)
            if key is None:
                continue
            for user in block.select(".participation-list-user"):
                name_el = user.select_one(".participation-list-user-name")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                uid = None
                a = user.find("a", href=re.compile(r"/user/view\?id=\d+"))
                if a:
                    uid = int(re.search(r"id=(\d+)", a["href"]).group(1))
                result["groups"][key].append({"name": name, "user_id": uid})
        return result

    # ----------------------------------------------------------------- helper
    @staticmethod
    def _find_login_form(soup: BeautifulSoup):
        # Bevorzugt ein Formular, das ein Passwortfeld enthaelt.
        for form in soup.find_all("form"):
            if form.find("input", {"type": "password"}):
                return form
        return soup.find("form")

    @staticmethod
    def _guess_field(form, keywords) -> str | None:
        # Erst per type, dann per name/id raten.
        if "password" in keywords:
            pw = form.find("input", {"type": "password"})
            if pw and pw.get("name"):
                return pw["name"]
        for inp in form.find_all("input"):
            name = (inp.get("name") or "") + " " + (inp.get("id") or "")
            itype = inp.get("type", "")
            if itype == "email" and "email" in keywords:
                return inp.get("name")
            if any(k in name.lower() for k in keywords):
                if inp.get("name"):
                    return inp["name"]
        return None

    @staticmethod
    def _form_error(html: str) -> str | None:
        """Fehlermeldung aus dem Login-Formular lesen (z. B. 'Passwort falsch')."""
        soup = BeautifulSoup(html, "html.parser")
        for sel in (".help-block-error", ".help-block", ".alert", "[class*=error]"):
            for node in soup.select(sel):
                txt = node.get_text(" ", strip=True)
                if txt:
                    return txt
        return None


if __name__ == "__main__":
    # Mini-Selbsttest: nur Login.
    import os

    email = os.environ.get("SP_EMAIL")
    pw = os.environ.get("SP_PASSWORD")
    if not email or not pw:
        print("Bitte SP_EMAIL und SP_PASSWORD als Umgebungsvariablen setzen.")
        sys.exit(1)
    sp = SpielerPlus(email, pw)
    sp.login()
    print("Login erfolgreich.")
