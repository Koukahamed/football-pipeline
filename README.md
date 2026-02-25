# ⚽ Football Weekly Pipeline

Pipeline de données automatisé qui publie chaque semaine un dashboard des stats football (EPL, Ligue 1, Bundesliga) sur GitHub Pages.

**→ [Voir le dashboard live](https://koukahamed.github.io/football-pipeline)**

## Ce que fait le pipeline

Chaque lundi à 8h UTC, GitHub Actions :

1. **Extrait** les données depuis [football-data.org](https://football-data.org) (API gratuite)
2. **Charge** dans DuckDB (data warehouse local)
3. **Transforme** avec dbt (staging → mart)
4. **Teste** la qualité des données (dbt tests)
5. **Génère** un dashboard HTML
6. **Publie** automatiquement sur GitHub Pages

## Stack technique

| Outil | Rôle |
|---|---|
| **GitHub Actions** | Orchestration / CI-CD |
| **Python + requests** | Extraction API |
| **DuckDB** | Data warehouse léger |
| **dbt Core** | Transformation SQL (staging → mart) |
| **HTML/CSS** | Dashboard statique |
| **GitHub Pages** | Publication automatique |

## Setup (5 minutes)

### 1. Fork le repo

```bash
git clone https://github.com/ton-user/football-pipeline.git
cd football-pipeline
```

### 2. Obtenir une clé API gratuite

→ S'inscrire sur [football-data.org](https://www.football-data.org/client/register) (gratuit, 10 req/min)

### 3. Ajouter le secret GitHub

Dans ton repo → **Settings → Secrets → Actions** :

```
Name  : FOOTBALL_API_KEY
Value : ta_clé_api
```

### 4. Activer GitHub Pages

Dans **Settings → Pages** → Source : `gh-pages` branch

### 5. Lancer manuellement

Dans l'onglet **Actions** → `Football Weekly Pipeline` → **Run workflow**

## Structure du projet

```
football-pipeline/
├── .github/
│   └── workflows/
│       └── weekly_pipeline.yml   # GitHub Actions — lundi 8h UTC
├── ingestion/
│   ├── fetch_data.py             # Extraction API football-data.org
│   └── load_duckdb.py            # Chargement DuckDB (couche raw)
├── dbt/
│   ├── models/
│   │   ├── staging/              # stg_standings, stg_matches
│   │   └── mart/                 # mart_league_summary
│   ├── tests/                    # assert_points_consistent.sql
│   ├── dbt_project.yml
│   └── profiles.yml
├── report/
│   └── generate_report.py        # Génère index.html → GitHub Pages
└── data/                         # DuckDB + JSON (gitignored)
```

## Modèles dbt

| Modèle | Couche | Description |
|---|---|---|
| `stg_standings` | Staging | Classements nettoyés + KPIs |
| `stg_matches` | Staging | Matchs terminés + résultats |
| `mart_league_summary` | Mart | Top 5 + stats hebdo par ligue |

## Data Quality

Tests automatisés à chaque run :
- Colonnes non nulles (positions, points, équipes)
- Valeurs acceptées (résultats : HOME_WIN, AWAY_WIN, DRAW)
- IDs de matchs uniques
- Cohérence points = victoires × 3 + nuls

---

**Auteur** : Hamed Savadogo — Data Engineer

[LinkedIn](https://linkedin.com/in/ton-profil) · [GitHub](https://github.com/ton-user)
