#!/usr/bin/env python3
"""Verifie que les services Good & Right repondent, et alerte par mail au changement d'etat.

Tourne dans GitHub Actions, donc en dehors de Railway : si Railway tombe, ce script
continue de tourner et peut prevenir. C'est tout l'interet.

Variables d'environnement attendues :
  BREVO_API_KEY  cle API Brevo (secret GitHub)
  ALERT_TO       destinataire des alertes (secret GitHub)
  ALERT_FROM     expediteur, doit etre un domaine verifie dans Brevo
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "targets.json"
STATE = ROOT / "state.json"

# Une seule tentative qui echoue ne declenche rien : un blip reseau ou un redemarrage
# de conteneur ne doit pas reveiller David un dimanche matin.
ATTEMPTS = 3
RETRY_WAIT = 6
TIMEOUT = 15


def probe(url, expect):
    """Retourne (ok, detail). Reessaie avant de conclure a une panne."""
    last = "aucune tentative"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "gr-uptime/1.0 (+github-actions)"},
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                code = resp.status
                # Railway renvoie ce header quand aucun service n'est attache au
                # domaine : c'est exactement la panne du 20 aout 2026.
                fallback = resp.headers.get("x-railway-fallback")
                if fallback:
                    last = f"HTTP {code}, aucun service Railway derriere le domaine"
                elif code == expect:
                    return True, f"HTTP {code}"
                else:
                    last = f"HTTP {code}, attendu {expect}"
        except urllib.error.HTTPError as exc:
            if exc.code == expect:
                return True, f"HTTP {exc.code}"
            last = f"HTTP {exc.code}"
        except urllib.error.URLError as exc:
            last = f"injoignable ({exc.reason})"
        except Exception as exc:  # noqa: BLE001
            last = f"erreur {type(exc).__name__}: {exc}"

        if attempt < ATTEMPTS:
            time.sleep(RETRY_WAIT)

    return False, last


def send_mail(subject, lines):
    key = os.environ.get("BREVO_API_KEY")
    to = os.environ.get("ALERT_TO")
    sender = os.environ.get("ALERT_FROM", to)
    if not key or not to:
        print("!! BREVO_API_KEY ou ALERT_TO absent, pas d'envoi de mail", file=sys.stderr)
        return False

    body = {
        "sender": {"email": sender, "name": "Monitoring Good & Right"},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": "\n".join(lines),
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(body).encode(),
        headers={
            "api-key": key,
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"mail envoye a {to} (HTTP {resp.status})")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"!! echec envoi mail : {exc}", file=sys.stderr)
        return False


def main():
    targets = json.loads(TARGETS.read_text())
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}

    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    current, went_down, came_back = {}, [], []

    for target in targets:
        name, url = target["name"], target["url"]
        ok, detail = probe(url, target.get("expect", 200))
        current[name] = {"up": ok, "detail": detail, "checked": now}

        was_up = previous.get(name, {}).get("up", True)
        print(f"{'OK  ' if ok else 'DOWN'}  {name:24s} {detail}")

        if was_up and not ok:
            went_down.append((name, url, detail))
        elif not was_up and ok:
            came_back.append((name, url))

    STATE.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n")

    # On n'envoie un mail que sur changement d'etat. Sinon une panne d'un week-end
    # produirait 200 mails identiques et on finirait par tous les ignorer.
    if went_down:
        noms = ", ".join(n for n, _, _ in went_down)
        lines = [f"Services hors ligne detectes le {now} :", ""]
        lines += [f"  - {n}\n    {u}\n    {d}\n" for n, u, d in went_down]
        lines += [
            "Verifier en priorite :",
            "  1. https://railway.com/workspace/billing  (plan actif ? carte valide ?)",
            "  2. https://railway.com/dashboard          (services en ligne ?)",
            "",
            "Rappel : le 20/08/2026 la panne venait d'un abonnement Railway annule",
            "pour impaye, pas d'un bug applicatif.",
        ]
        send_mail(f"[ALERTE] {noms} hors ligne", lines)

    if came_back:
        noms = ", ".join(n for n, _ in came_back)
        lines = [f"Retour en ligne le {now} :", ""]
        lines += [f"  - {n}\n    {u}\n" for n, u in came_back]
        send_mail(f"[OK] {noms} de nouveau en ligne", lines)

    down = [n for n, s in current.items() if not s["up"]]
    if down:
        # Sortie en erreur : GitHub marque le run en rouge et envoie sa propre
        # notification, ce qui fait un deuxieme canal si Brevo est indisponible.
        print(f"\n{len(down)} service(s) hors ligne : {', '.join(down)}", file=sys.stderr)
        return 1

    print(f"\nTous les services repondent ({len(targets)} verifies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
