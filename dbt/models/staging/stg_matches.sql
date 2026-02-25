SELECT
    league,
    match_id,
    CAST(match_date AS TIMESTAMP) AS match_date,
    home_team,
    away_team,
    home_score,
    away_score,
    matchday,
    CASE
        WHEN home_score > away_score THEN 'HOME_WIN'
        WHEN home_score < away_score THEN 'AWAY_WIN'
        WHEN home_score = away_score THEN 'DRAW'
        ELSE 'UNKNOWN'
    END AS result,
    COALESCE(home_score, 0) + COALESCE(away_score, 0) AS total_goals,
    extracted_at
FROM raw.matches
WHERE status = 'FINISHED'
  AND home_score IS NOT NULL
  AND away_score IS NOT NULL
