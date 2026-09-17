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

## Surveillance SEO du site vitrine

Depuis le 17/09/2026, `targets.json` surveille aussi deux fichiers de `goodandright.fr`
qui ne sont pas des services mais qui conditionnent la visibilite du site :
`sitemap.xml` et `robots.txt`.

Ces deux cibles utilisent deux options supplementaires, facultatives, que les cibles
de disponibilite n'ont pas besoin de declarer :

- `must_contain` : liste de chaines qui doivent apparaitre dans le corps de la reponse.
- `min_count` : nombre minimal d'occurrences attendues, par chaine.

Le corps n'est telecharge que pour les cibles qui declarent l'une de ces deux options.

### Pourquoi tester le contenu et pas seulement le code HTTP

Entre novembre 2025 et septembre 2026, la generation du sitemap etait desactivee dans
Webflow. Consequence : 13 des 20 pages Management de transition n'ont jamais ete
explorees par Google, et le site n'apparaissait sur aucune requete commerciale.
Dix mois, sur des pages payees.

Un moniteur qui ne regarde que le code de retour n'aurait rien vu, pour une raison
precise : `robots.txt` repondait **HTTP 200 avec un corps de zero octet**. Statut
parfaitement valide, fichier parfaitement inutile.

D'ou les assertions de contenu. Les quatre modes de defaillance couverts :

| Situation | Ce qui la detecte |
|---|---|
| `robots.txt` vide ou sans directive `Sitemap:` | `must_contain` |
| `sitemap.xml` qui sert la page 404 HTML de Webflow en 200 | `must_contain` sur `<urlset` |
| sitemap valide mais ampute des pages Management de transition | `min_count` sur `management-de-transition` |
| sitemap effondre a quelques URLs | `min_count` sur `<loc>` |

### Seuils

46 URLs au 17/09/2026, dont 21 sous `/management-de-transition/`. Les seuils sont
fixes a 40 et 20, sous les valeurs reelles : la suppression volontaire d'une page
isolee ne doit pas declencher d'alerte, l'effondrement du sitemap si.

A relever a la hausse si le site grossit franchement, sinon le test perd son pouvoir
de detection.

### Ce qui n'est volontairement pas surveille ici

Le `hreflang` des pages Management de transition est actuellement faux : les balises
declarent que l'equivalent francais de chaque page est la page d'accueil. La correction
est en attente chez l'agence. Ajouter ce test maintenant ferait passer le moniteur au
rouge en permanence, ce qui detruirait la valeur du signal : un run rouge doit vouloir
dire quelque chose. **A ajouter une fois la correction en ligne**, sous la forme d'un
`must_contain` sur `hreflang="fr-FR"` dans une page MT.

Le nombre de pages indexees par Google n'est pas surveille non plus : cela demanderait
l'API Search Console et une authentification de service, hors perimetre d'un moniteur
qui doit rester lisible et sans dependance.

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
le mail Resend, et le run GitHub qui passe au rouge (GitHub envoie sa propre notification).

Et si le canal mail tombe, le run passe au rouge lui aussi. Un moniteur dont l'alerte
ne part plus est en panne, meme quand tous les services repondent : c'est exactement ce
qui s'est produit du 22/08 au 02/09/2026 sans que rien ne le signale.

L'envoi passe par Resend et non par Brevo : le compte Brevo restreint ses cles API a une
liste d'IP autorisees, or les runners GitHub Actions changent d'IP a chaque run. Tous les
envois repondaient 401 depuis la creation du repo. Ne pas y revenir sans desactiver
d'abord cette restriction cote Brevo.

## Configuration

Trois secrets a definir dans `Settings > Secrets and variables > Actions` :

| Secret | Role |
|---|---|
| `RESEND_API_KEY` | Cle API Resend pour l'envoi |
| `ALERT_TO` | Destinataire des alertes |
| `ALERT_FROM` | Expediteur, doit etre sur un domaine verifie dans Resend |

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
