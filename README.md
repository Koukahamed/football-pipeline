# ⚽ Football Daily Digest

Pipeline automatisé qui tourne **chaque matin à 8h UTC** et envoie un **email HTML** récapitulatif avec :

- 📅 **Matchs du jour** — coup d'envoi heure UTC, par ligue
- 🏆 **Récap d'hier** — scores
- ⚽ **Top 5 scoreurs** — par ligue

**Ligues couvertes :** 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League · 🇫🇷 Ligue 1 · 🇩🇪 Bundesliga · 🇪🇸 La Liga

---

## 🗂️ Structure

```
├── ingestion/
│   └── fetch_data.py          # Fetch API football-data.org (aujourd'hui + hier)
├── report/
│   └── send_email.py          # Génère le HTML et envoie via SMTP
└── .github/workflows/
    └── daily_pipeline.yml     # GitHub Actions — tourne chaque matin
```

---

## ⚙️ Configuration — GitHub Secrets

Dans **Settings → Secrets and variables → Actions**, ajouter :

| Secret            | Description                                        | Exemple                    |
|-------------------|----------------------------------------------------|----------------------------|
| `FOOTBALL_API_KEY`| Clé API football-data.org                          | `abc123xyz`                |
| `SMTP_HOST`       | Serveur SMTP                                       | `smtp.gmail.com`           |
| `SMTP_PORT`       | Port SMTP (STARTTLS)                               | `587`                      |
| `SMTP_USER`       | Login SMTP (ton adresse Gmail)                     | `moi@gmail.com`            |
| `SMTP_PASS`       | Mot de passe applicatif Gmail (App Password)       | `xxxx xxxx xxxx xxxx`      |
| `EMAIL_FROM`      | Expéditeur affiché                                 | `Football Daily <moi@gmail.com>` |
| `EMAIL_TO`        | Destinataire(s) séparés par virgule                | `moi@gmail.com,ami@gmail.com` |

### Gmail — App Password

1. Activer la validation en deux étapes sur ton compte Google
2. Aller sur https://myaccount.google.com/apppasswords
3. Créer un mot de passe pour "Mail" → copier les 16 caractères dans `SMTP_PASS`

---

## 🚀 Lancement

**Automatique :** tous les matins à 8h UTC via GitHub Actions.

**Manuel :** dans l'onglet **Actions** → `⚽ Football Daily Digest` → **Run workflow**.
Options :
- `preview_only: true` → génère le HTML sans envoyer l'email (l'artifact est téléchargeable)

**Local :**
```bash
pip install requests
export FOOTBALL_API_KEY=ta_cle
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=moi@gmail.com
export SMTP_PASS=xxxx_xxxx_xxxx_xxxx
export EMAIL_TO=moi@gmail.com

python ingestion/fetch_data.py
python report/send_email.py
```

---

## 🔑 API football-data.org

- Plan gratuit disponible sur https://www.football-data.org/
- Limite : 10 requêtes/minute (délai de 7s géré automatiquement)
- Le plan gratuit donne accès aux standings, matchs et scoreurs des principales ligues

---

## 📬 Aperçu de l'email

L'email HTML s'adapte aux dark/light modes et est compatible Gmail, Outlook, Apple Mail.
Un fichier `report/output/email_preview.html` est également uploadé en artifact GitHub à chaque run.
