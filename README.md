# ⚽ Football Daily

Un mail court le matin et un dashboard public issu de la même extraction : résultats, matchs du jour, calendrier sur sept jours, classements, buteurs et équipes favorites.

[Ouvrir le dashboard](https://koukahamed.github.io/football-pipeline/)

## Fonctionnement

`ingestion/fetch_data.py` → JSON dans `data/raw` → `report/send_email.py` et `report/generate_dashboard.py`.

Le workflow **Football Daily Digest** utilise deux cron UTC (07 h et 08 h) et ne poursuit que pendant l’heure de 09 h en `Europe/Paris`. GitHub Actions peut retarder un déclenchement : l’horaire n’est pas une garantie à la minute. Un lancement manuel contourne ce contrôle. Une modification des sources sur `main` actualise aussi le dashboard, sans envoyer de mail supplémentaire.

Les dates de match sont filtrées dans le fuseau de Paris, y compris autour de minuit et des changements d’heure. Les requêtes couvrent sept jours passés et sept jours à venir ; le dashboard ne prétend pas fournir des scores en direct. Les statistiques détaillées dépendent des données accessibles avec le compte API.

Les réponses API réussies sont enregistrées atomiquement. Une erreur conserve la dernière réponse réussie et figure dans les métadonnées ; une panne complète bloque le mail et la publication. Les réponses 429 et erreurs serveur sont retentées avec temporisation. Le débit est limité à moins de 10 appels/minute. Aucune requête supplémentaire par match n’est nécessaire pour cette version.

## Configuration

Modifier `config.json` :

- `leagues` : compétitions communes au mail et au dashboard ; leurs codes doivent être accessibles avec le plan football-data.org utilisé.
- `favorite_team_ids` : IDs football-data.org des équipes suivies dans le mail. Liste vide par défaut, aucun club choisi implicitement.
- `dashboard_url` : URL GitHub Pages du dépôt.
- `timezone` : `Europe/Paris` pour cette installation ; l’interface et le workflow utilisent également ce fuseau.

Les étoiles du dashboard enregistrent des favoris **dans le navigateur**. Elles ne changent pas les favoris du mail, définis dans le fichier de configuration.

Configurer les secrets GitHub Actions : `FOOTBALL_API_KEY`, `SMTP_HOST`, `SMTP_PORT` (587 par défaut), `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM` (optionnel), `EMAIL_TO` (adresses séparées par des virgules). SMTP utilise STARTTLS. Un échec d’envoi fait échouer le job.

Dans **Settings → Pages**, conserver la publication depuis la branche `gh-pages`, dossier racine. Cette branche contient exclusivement les fichiers générés : ne pas ouvrir de PR `gh-pages` → `main`.

## Exécution et aperçu

**Actions → Football Daily Digest → Run workflow** : `preview_only` vaut **true par défaut**. Il génère l’artifact `football-preview` sans envoyer de mail, modifier le cache de production ou publier. Décocher pour envoyer et publier depuis `main`.

```bash
pip install -r requirements.txt
export FOOTBALL_API_KEY=...
python ingestion/fetch_data.py
python report/send_email.py --preview-only
python report/generate_dashboard.py
python -m http.server --directory report/output 8000
```

L’aperçu du mail est `report/output/email_preview.html`. Il est disponible dans les artifacts, mais retiré avant publication sur Pages. Les secrets SMTP et destinataires ne sont jamais ajoutés au dashboard.

## Historique et limites

Les données et snapshots J−1 sont restaurés et sauvegardés via le cache Actions, conservant jusqu’à 60 jours de snapshots. Le cache peut être évincé par GitHub : une variation de classement absente est affichée `—`, jamais inventée. Ce stockage convient à ce petit produit ; un historique durable nécessiterait un stockage dédié.

L’ancien dossier dbt reste conservé pour le moment, mais n’est plus exécuté par le digest. Le dashboard ne reprend pas le HTML figé de février 2026.

## Vérifications

```bash
python -m unittest discover -s tests -v
python -m compileall -q ingestion report
```

Le workflow `Checks` exécute ces tests et vérifie la syntaxe JavaScript sur les PR et les commits de `main`. Les tests n’appellent ni l’API réelle ni SMTP.
