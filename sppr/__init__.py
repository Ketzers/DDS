"""
sppr — модули системы поддержки принятия решений.

    survey_metrics   — метрики опроса целевой аудитории
    metro_stations   — справочник станций Московского метрополитена
    scoring          — скоринговый движок: 4 критерия + рекомендации
"""

from sppr.survey_metrics import SurveyMetrics, load_survey_metrics
from sppr.metro_stations import (
    MetroStation, METRO_STATIONS,
    find_station, get_station_names, find_quiet_stations, haversine_km,
)
from sppr.scoring import (
    ProjectInput, ProjectScore, CriterionScore, Improvement, Strategy,
    evaluate_project, suggest_improvements, suggest_combined_strategy,
    predict_occupancy, detect_genre,
    compute_weights, DEFAULT_CRITERION_WEIGHTS,
)

__all__ = [
    # survey
    'SurveyMetrics', 'load_survey_metrics',
    # metro
    'MetroStation', 'METRO_STATIONS',
    'find_station', 'get_station_names', 'find_quiet_stations', 'haversine_km',
    # scoring
    'ProjectInput', 'ProjectScore', 'CriterionScore', 'Improvement', 'Strategy',
    'evaluate_project', 'suggest_improvements', 'suggest_combined_strategy',
    'predict_occupancy', 'detect_genre',
]
