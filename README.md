# gr-uptime

Surveillance externe des services Good & Right.

## Pourquoi ce repo existe

Le 20 aout 2026, l'abonnement Railway a ete annule pour impaye. Le CRM, le blog et
le diagnostic e-facture sont tombes. La panne a ete decouverte deux jours plus tard,
par hasard, en essayant de se connecter.

L'alerting existant n'a rien signale, pour une raison structurelle : il tourne sur
Railway. Un moniteur heberge sur l'infrastructure qu'il surveille ne peut pas prevenir
que cette infrastructure est morte.

D'ou ce repo. Il tourne sur GitHub Actions, c'est-a-dire ailleurs.

## Fonctionnement

`scripts/check.py` interroge chaque URL de `targets.json` toutes les 15 minutes.

- **3 tentatives espacees de 6 s** avant de conclure a une panne, pour ne pas alerter
  sur un redemarrage de conteneur ou un blip reseau.
- Detection du header `x-railway-fallback`, que Railway renvoie quand plus aucun
  service n'est attache au domaine. C'est la signature exacte de la panne d'aout 2026 :
  sans ce test, un `404` applicatif et un service disparu seraient indiscernables.
- **Alerte uniquement au changement d'etat**, via `state.json`. Une panne de week-end
  enverrait sinon 200 mails identiques, qu'on finirait par ignorer.
- Un mail est aussi envoye au retour a la normale.

Deux canaux de notification, pour que la panne d'un canal ne masque pas la panne reelle :
le mail Brevo, et le run GitHub qui passe au rouge (GitHub envoie sa propre notification).

## Configuration

Trois secrets a definir dans `Settings > Secrets and variables > Actions` :

| Secret | Role |
|---|---|
| `BREVO_API_KEY` | Cle API Brevo pour l'envoi |
| `ALERT_TO` | Destinataire des alertes |
| `ALERT_FROM` | Expediteur, doit etre un domaine verifie dans Brevo |

Pour surveiller un service de plus, ajouter une entree dans `targets.json`. Rien d'autre.

## Limites connues

- Les crons GitHub Actions sont parfois retardes en periode de charge. Compter 15 a
  30 minutes entre la panne reelle et l'alerte.
- GitHub desactive les workflows planifies apres 60 jours sans activite sur le repo.
  Les commits de `state.json` par le bot devraient suffire a maintenir l'activite,
  mais c'est a verifier au bout de deux mois.
- Ce repo verifie qu'une page repond. Il ne verifie pas qu'elle est correcte.
- Le Declic est surveille via son URL Railway directe, pas via
  `declic.goodandright.fr`. Le domaine personnalise a saute le 22/08/2026 :
  CNAME et TXT de verification absents de la zone Gandi, domaine detache cote
  Railway. L'application tourne toujours. A rebasculer sur le domaine custom
  une fois celui-ci remis en service.
