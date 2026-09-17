#!/usr/bin/env python3
"""Verifie que les services Good & Right repondent, et alerte par mail au changement d'etat.

Tourne dans GitHub Actions, donc en dehors de Railway : si Railway tombe, ce script
continue de tourner et peut prevenir. C'est tout l'interet.

Variables d'environnement attendues :
  RESEND_API_KEY  cle API Resend (secret GitHub)
  ALERT_TO        destinataire des alertes (secret GitHub)
  ALERT_FROM      expediteur, doit etre sur un domaine verifie dans Resend

Resend et non Brevo : le compte Brevo restreint ses cles API a une liste d'IP
autorisees, et les runners GitHub Actions changent d'IP a chaque run. L'envoi
echouait donc systematiquement en 401 depuis la creation du repo, sans que
personne ne le voie.
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


def verifier_contenu(body, must_contain, min_count):
    """Retourne None si le contenu est conforme, sinon la raison de l'echec.

    Un code HTTP 200 ne dit pas si le fichier fait son travail. Le robots.txt de
    goodandright.fr a longtemps repondu 200 avec un corps de zero octet, et un
    moniteur qui ne regarde que le statut l'aurait declare en bonne sante. De meme,
    un sitemap peut repondre 200 en ne listant plus aucune URL.
    """
    for aiguille in must_contain or []:
        if aiguille not in body:
            return f"« {aiguille} » absent du contenu"
    for aiguille, minimum in (min_count or {}).items():
        trouve = body.count(aiguille)
        if trouve < minimum:
            return f"{trouve} occurrence(s) de « {aiguille} », minimum attendu {minimum}"
    return None


def probe(url, expect, must_contain=None, min_count=None):
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
                elif code != expect:
                    last = f"HTTP {code}, attendu {expect}"
                elif not (must_contain or min_count):
                    return True, f"HTTP {code}"
                else:
                    # Corps lu uniquement quand une cible declare des assertions,
                    # pour ne pas telecharger les pages HTML des autres cibles.
                    body = resp.read().decode("utf-8", "replace")
                    probleme = verifier_contenu(body, must_contain, min_count)
                    if probleme is None:
                        return True, f"HTTP {code}, contenu conforme"
                    last = f"HTTP {code} mais {probleme}"
        except urllib.error.HTTPError as exc:
            # Un statut attendu mais servi via une erreur HTTP ne permet pas de
            # verifier les assertions de contenu : on ne conclut pas au succes.
            if exc.code == expect and not (must_contain or min_count):
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
    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("ALERT_TO")
    sender = os.environ.get("ALERT_FROM", to)
    if not key or not to:
        print("!! RESEND_API_KEY ou ALERT_TO absent, pas d'envoi de mail", file=sys.stderr)
        return False

    body = {
        "from": f"Monitoring Good & Right <{sender}>",
        "to": [to],
        "subject": subject,
        "text": "\n".join(lines),
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(body).encode(),
        headers={
            "authorization": f"Bearer {key}",
            "content-type": "application/json",
            # Sans User-Agent explicite, urllib s'annonce "Python-urllib/3.x" et le
            # Cloudflare devant l'API Resend repond 403 code 1010.
            "user-agent": "gr-uptime/1.0 (+github-actions)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"mail envoye a {to} (HTTP {resp.status})")
            return True
    except urllib.error.HTTPError as exc:
        # Le code seul ne suffit pas a diagnostiquer : un 401 peut venir d'une cle
        # revoquee comme d'une restriction d'IP, et un 403 d'un domaine expediteur
        # non verifie. Seul le corps de la reponse fait la difference.
        try:
            body = exc.read().decode(errors="replace")[:500]
        except Exception:  # noqa: BLE001
            body = "(corps illisible)"
        print(f"!! echec envoi mail : HTTP {exc.code} {body}", file=sys.stderr)
        return False
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
        ok, detail = probe(
            url,
            target.get("expect", 200),
            target.get("must_contain"),
            target.get("min_count"),
        )
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
    mail_failed = False

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
        if not send_mail(f"[ALERTE] {noms} hors ligne", lines):
            mail_failed = True

    if came_back:
        noms = ", ".join(n for n, _ in came_back)
        lines = [f"Retour en ligne le {now} :", ""]
        lines += [f"  - {n}\n    {u}\n" for n, u in came_back]
        if not send_mail(f"[OK] {noms} de nouveau en ligne", lines):
            mail_failed = True

    down = [n for n, s in current.items() if not s["up"]]
    if down:
        # Sortie en erreur : GitHub marque le run en rouge et envoie sa propre
        # notification, ce qui fait un deuxieme canal si le mail est indisponible.
        print(f"\n{len(down)} service(s) hors ligne : {', '.join(down)}", file=sys.stderr)
        return 1

    if mail_failed:
        # Un canal d'alerte muet est une panne a part entiere. Sans cette sortie en
        # erreur, l'echec d'envoi ne serait visible que dans un log de run vert, que
        # personne ne lit : c'est precisement ce qui a masque le blocage Brevo
        # pendant onze jours.
        print(
            "\nTous les services repondent, mais une alerte n'a pas pu etre envoyee. "
            "Le canal mail est hors service, voir l'erreur ci-dessus.",
            file=sys.stderr,
        )
        return 1

    print(f"\nTous les services repondent ({len(targets)} verifies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
