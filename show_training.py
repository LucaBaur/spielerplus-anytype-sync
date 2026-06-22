"""
Schritt 2 – Demo: Trainings eines Teams mit Zu-/Absagen anzeigen.

    py show_training.py                 # Teams + naechste Termine auflisten
    py show_training.py --event 76263482        # ein Training im Detail
    py show_training.py --event 76263482 --type training --json

Liest aus .env: SP_EMAIL, SP_PASSWORD und optional SP_TEAM_ID.
"""
import argparse
import json
import sys

from spielerplus import SpielerPlus, SpielerPlusError
from test_login import load_env

# Konsole auf UTF-8 stellen, damit Umlaute/Emojis nicht abstuerzen.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", type=int, default=None, help="Event-ID")
    ap.add_argument("--type", default="training", help="Event-Typ (training/game)")
    ap.add_argument("--team", type=int, default=None, help="Team-ID (switch-user)")
    ap.add_argument("--json", action="store_true", help="Rohausgabe als JSON")
    args = ap.parse_args()

    env = load_env()
    sp = SpielerPlus(env.get("SP_EMAIL"), env.get("SP_PASSWORD"))
    try:
        sp.login()
    except SpielerPlusError as e:
        print(f"FEHLER beim Login: {e}")
        return
    print("Login OK.\n")

    # Teams anzeigen
    teams = sp.list_teams()
    print("Teams deines Accounts:")
    for t in teams:
        print(f"  - {t['name']}  (id={t['id']})")
    print()

    # Team waehlen: Argument > .env > erstes Team in der Liste
    team_id = args.team or (int(env["SP_TEAM_ID"]) if env.get("SP_TEAM_ID") else None)
    if not team_id:
        team_id = teams[0]["id"] if teams else None
    if team_id:
        name = next((t["name"] for t in teams if t["id"] == team_id), "?")
        print(f"-> Wechsle auf Team: {name} (id={team_id})\n")
        sp.switch_team(team_id)

    # Termine auflisten
    events = sp.list_events()
    print(f"Naechste Termine ({len(events)}):")
    for e in events:
        print(f"  [{e['type']}] id={e['id']}  {e['weekday']} {e['day']}  {e['title']}")
    print()

    # Ein konkretes Training im Detail
    event_id = args.event or (events[0]["id"] if events else None)
    event_type = args.type
    if args.event is None and events:
        event_type = events[0]["type"]
    if not event_id:
        print("Keine Termine vorhanden.")
        return

    part = sp.get_participation(event_type, event_id)
    if args.json:
        print(json.dumps(part, ensure_ascii=False, indent=2))
        return

    g = part["groups"]
    print("=" * 50)
    print(f"{part['title']}  –  {part['datetime']}  (id={event_id})")
    print("=" * 50)
    for key, label in (("zugesagt", "ZUGESAGT"), ("unsicher", "UNSICHER"),
                       ("abgesagt", "ABGESAGT"), ("offen", "NOCH OFFEN"),
                       ("nicht_nominiert", "NICHT NOMINIERT")):
        leute = g[key]
        print(f"\n{label} ({len(leute)}):")
        for p in leute:
            print(f"  - {p['name']}  (user_id={p['user_id']})")


if __name__ == "__main__":
    main()
