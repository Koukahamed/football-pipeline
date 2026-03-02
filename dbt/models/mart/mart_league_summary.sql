-- models/mart/mart_league_summary.sql
-- Table finale : top 5 par ligue + stats de la semaine

WITH standings AS (
    SELECT * FROM {{ ref('stg_standings') }}
),

matches AS (
    SELECT * FROM {{ ref('stg_matches') }}
),

-- Stats des matchs de la semaine par ligue
week_stats AS (
    SELECT
        league,
        COUNT(*)                            AS matches_played,
        SUM(total_goals)                    AS total_goals,
        ROUND(AVG(total_goals), 2)          AS avg_goals_per_match,
        COUNT(*) FILTER (WHERE result = 'HOME_WIN') AS home_wins,
        COUNT(*) FILTER (WHERE result = 'AWAY_WIN') AS away_wins,
        COUNT(*) FILTER (WHERE result = 'DRAW')     AS draws,
        MAX(total_goals)                    AS highest_scoring_match
    FROM matches
    GROUP BY league
),

-- Top 5 classement par ligue
top5 AS (
    SELECT *
    FROM standings
    WHERE position <= 5
),

final AS (
    SELECT
        t.*,
        w.matches_played        AS week_matches,
        w.total_goals           AS week_goals,
        w.avg_goals_per_match,
        w.home_wins,
        w.away_wins,
        w.draws,
        w.highest_scoring_match
    FROM top5 t
    LEFT JOIN week_stats w USING (league)
)

SELECT * FROM final
ORDER BY league, position
