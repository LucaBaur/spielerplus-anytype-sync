# SpielerPlus → Anytype Sync

Liest die Trainings-Zu-/Absagen eines Teams aus [SpielerPlus](https://www.spielerplus.de)
aus und überträgt sie in [Anytype](https://anytype.io): pro Training werden die
anwesenden und abgesagten Spieler:innen verknüpft und eine Übersichtstabelle
„Zusagen nach Position" in das Trainingsdokument geschrieben.

> ⚠️ **Inoffiziell.** SpielerPlus stellt keine öffentliche API bereit. Dieses
> Tool meldet sich wie ein Browser mit deinen Zugangsdaten an und liest die
> Webseiten aus. Das kann sich jederzeit ändern, wenn SpielerPlus die Seiten
> umbaut. Nutze es nur mit deinem eigenen Account, sparsam (z. B. 1×/Tag) und
> auf eigene Verantwortung. Prüfe die SpielerPlus-Nutzungsbedingungen.

## Funktionen

- Login bei SpielerPlus (E-Mail/Passwort, **ohne 2FA**) und Team-Auswahl
- Auslesen der Termine und der Teilnahme (Zugesagt / Unsicher / Abgesagt /
  Nicht nominiert) je Training
- Schreiben nach Anytype über die **lokale API**:
  - Datum (lokale Zeit), Anwesend, Abgesagt, SpielerPlus-Event-ID
  - Textkörper mit Tabelle „Zusagen nach Position" inkl. Kurz-Zusammenfassung
    (Zugesagt gesamt / Torhüter / Feldspieler)
- Abgleich nach Tag: bestehendes Training am selben Datum wird wiederverwendet;
  vorhandener Dokument-Inhalt bleibt erhalten (Tabelle wird oben eingefügt)
- Wahlweise **GUI** (Tkinter) oder Kommandozeile

## Voraussetzungen

- **Python 3.11+**
- **Anytype Desktop**, geöffnet/laufend (die lokale API hört auf
  `127.0.0.1:31009`)
- Ein **Anytype-API-Key** (Einstellungen → API Keys)
- Ein **SpielerPlus-Account ohne 2-Faktor-Authentifizierung**
- Python-Pakete: `requests`, `beautifulsoup4`

### Benötigtes Anytype-Datenmodell

Im Ziel-Space müssen folgende Typen/Eigenschaften existieren (Property-Keys in
Klammern – diese verwendet das Skript):

**Typ „Spieler"**
- `SpielerPlus-ID` (`spielerplus_id`, Text) – verknüpft eine Spielerin mit ihrer
  SpielerPlus-User-ID
- optional `Position Angriff` (`position_angriff`, Text) – für die
  Positions-Tabelle (z. B. „Tor", „Mitte", „Außen", „Kreis")

**Typ „Training"**
- `Datum` (`datum`, Date)
- `Anwesend` (`teilnehmer`, Objects → Spieler)
- `Abgesagt` (`abgesagt`, Objects → Spieler)
- `SpielerPlus-Event-ID` (`spielerplus_event_id`, Text)

Jede Spielerin muss einmalig ihre SpielerPlus-User-ID in `spielerplus_id`
bekommen (die User-ID steht in den ausgelesenen Teilnahmedaten).

## Einrichtung

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

`.env` ausfüllen (`SP_EMAIL`, `SP_PASSWORD`, `SP_TEAM_ID`, `Api_key`,
`ANYTYPE_SPACE_ID`). Mit `py show_training.py` werden deine Teams samt IDs
aufgelistet – die passende Team-ID trägst du als `SP_TEAM_ID` ein.

## Nutzung

### GUI (einfachster Weg)

```bash
py gui.py        # oder Doppelklick auf start_gui.pyw (ohne Konsolenfenster)
```

1. Es werden die Trainings der aktuellen Woche angezeigt.
2. Training anklicken → **Auswählen**.
3. Anytype wird geprüft:
   - kein Training an dem Tag → „Neues Training erstellen?"
   - Training vorhanden → „Anwesenheit erstellen/aktualisieren?"

### Kommandozeile

```bash
py test_login.py                       # nur Login testen
py show_training.py                    # Teams + nächste Termine + 1. Training
py show_training.py --event <ID>       # ein bestimmtes Training anzeigen

py sync.py --dry-run                   # Probelauf, nichts schreiben
py sync.py --limit 1                   # nur das nächste Training schreiben
py sync.py                             # alle kommenden Trainings
py sync.py --exclude <user_id[,…]>     # Spieler:innen für diesen Lauf als
                                       # kurzfristige Absage behandeln
```

## Funktionsweise

1. **SpielerPlus:** Login über das Login-Formular (CSRF-Token wird automatisch
   ausgelesen), Team-Wechsel, Terminliste (`/events/index`) und Teilnahme je
   Termin (`/events/ajaxgetparticipation`).
2. **Zuordnung:** SpielerPlus-User-IDs werden über die Eigenschaft
   `spielerplus_id` den Anytype-Spieler-Objekten zugeordnet.
3. **Schreiben:** Zielobjekt per SpielerPlus-Event-ID, sonst per Datum (gleicher
   Tag), sonst neu anlegen. Die Tabelle kommt oben in den Textkörper, vorhandener
   Inhalt bleibt erhalten; eine frühere Sync-Tabelle wird ersetzt.

## Projektdateien

| Datei              | Zweck                                                |
|--------------------|------------------------------------------------------|
| `spielerplus.py`   | SpielerPlus-Client (Login, Team, Termine, Teilnahme) |
| `anytype.py`       | Client für die lokale Anytype-API                    |
| `sync.py`          | Sync-Logik + Kommandozeile                           |
| `gui.py`           | Tkinter-Oberfläche                                   |
| `start_gui.pyw`    | Doppelklick-Starter für die GUI                      |
| `show_training.py` | Hilfsskript: Teams/Termine/Teilnahme anzeigen        |
| `test_login.py`    | Login-Test                                           |

## Lizenz

MIT – siehe [LICENSE](LICENSE).
