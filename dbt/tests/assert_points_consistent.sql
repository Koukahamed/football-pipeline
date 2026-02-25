SELECT team_name, league, points, won, draw,
       (won * 3 + draw) AS expected_points
FROM {{ ref('stg_standings') }}
WHERE points != (won * 3 + draw)
  AND played > 0
