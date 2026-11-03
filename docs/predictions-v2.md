# Predictions V2
The daily workflow backfills three completed seasons across PL, FL1, BL1, PD, CL, SA, PPL and DED. Scores are deduplicated by match id; extra time, awarded fixtures, incomplete scores and future games are excluded. Raw historical rows and coverage are persisted under data/training on the football-data branch.

## Features and models
Elo ratings start at 1500, use K=24 and a 60-point home adjustment, with a 15% regression toward 1500 per season. These initial settings are fixed design choices, not claimed optimized. A logistic reference learns 1/N/2 from Elo difference. Features for CatBoost also include recent goals for/against, recent points, known completed-match rest and congestion. All domestic and European matches collected contribute to each team's state; no hardcoded club favoritism.

Joint Dixon-Coles maximum likelihood learns team attack/defense, competition intercepts, home advantage, rest coefficient and low-score correlation with L2 regularization. Its challenger adds Elo difference. Numerical bounds ensure valid low-score probabilities. CatBoost uses 250 depth-4 trees with shrinkage and fixed seed. Ensembles are fixed equal-weight candidates, not optimized on the final test.

## Chronology
For a 2026/27 deployment: 2023/24 supplies initial history; 2024/25 selects candidates; Aug-Dec 2025 calibrates; Jan-Jun 2026 is the untouched final test. Parameters are refit on an expanding history before each evaluation month. Features for all matches on one UTC date are computed before that date's results update Elo or form. Historical final scores may contain later corrections: this is a retrospective simulation, not a point-in-time data archive.

Outcome selection minimizes validation log-loss; goal selection minimizes mean Brier across over 1.5/2.5/3.5. Outcome temperature and a common goal-grid temperature are learned only on the calibration segment. Goal-grid calibration preserves monotone thresholds. Before/after test metrics, reliability bins, competition breakdown and references are published. No perfect calibration is claimed.

A predeclared promotion gate requires candidate outcome log-loss no worse than both Elo and fixed frequencies and Brier no worse than Elo. Goals must beat the global Poisson reference. Failure retains the corresponding reference and is explicitly reported. The test is never used to adjust parameters. Future forecasts refit the approved recipe to available completed data (excluding the current UTC date).

## Versions and news
V1 predictions are preserved. Before kickoff only, V2 can issue a distinct revision; prior probabilities remain accessible in the archived versions. Subsequent V2 runs freeze the original V2 prediction. Every version is settled separately and prospective metrics stay separate from historical backtests.

Lineup access is probed on recent completed matches (counts only). Historical access does not prove timely pre-match publication. Injuries, uncertain players, expected lineups and rotations are not inferred or applied without an available source and validation. No paid service or new credential is configured automatically. Missing data never means zero absences.

The styled email cards are preserved. Model reports are public sporting/aggregate data only; SMTP configuration and recipient addresses are never included.
