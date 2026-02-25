-- models/staging/stg_standings.sql

SELECT
    league,
    position,
    team_id,
    team_name,
    played,
    won,
    draw,
    lost,
    goals_for,
    goals_against,
    goal_diff,
    points,
    -- KPIs dérivés
    ROUND(100.0 * won / NULLIF(played, 0), 1)   AS win_rate_pct,
    ROUND(goals_for::FLOAT / NULLIF(played, 0), 2) AS goals_per_game,
    extracted_at

FROM raw.standings
WHERE team_name IS NOT NULL