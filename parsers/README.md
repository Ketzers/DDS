# parsers/

Скрипты сбора данных для СППР по квест-комнатам Москвы. Все парсеры
работают с публичным агрегатором mir-kvestov.ru и сторонними геосервисами.

## Состав

| Файл | Что делает | Вход | Выход |
|---|---|---|---|
| `parse_quests.py` | Парсинг каталога и карточек квестов | — | `quests_data.xlsx` |
| `geocode_quests.py` | Геокодинг адресов через Nominatim | `mir_kvestov_top100.xlsx` | `mir_kvestov_top100_geo.xlsx` |
| `parse_slots.py` | Парсинг расписания и слотов бронирования | `mir_kvestov_full.xlsx` | `slots.xlsx` |
| `parse_reviews.py` | Парсинг отзывов с карточек квестов | `mir_kvestov_full.xlsx` | `reviews.xlsx`, `reviews_stats.xlsx` |
| `sentiment_analysis.py` | Словарный анализ тональности отзывов | `reviews.xlsx` | `reviews_sentiment.xlsx`, `quest_sentiment.xlsx` |

## Порядок запуска

Скрипты должны запускаться последовательно — каждый следующий использует
выход предыдущего:

```
1. parse_quests.py        →  quests_data.xlsx
2. geocode_quests.py      →  + колонки lat, lon, geo_source
3. parse_slots.py         →  slots.xlsx (расписание для каждого квеста)
4. parse_reviews.py       →  reviews.xlsx (тексты отзывов)
5. sentiment_analysis.py  →  reviews_sentiment.xlsx, quest_sentiment.xlsx
```

После выполнения всех шагов промежуточные результаты объединяются в
итоговый файл `mir_kvestov_full.xlsx`, на котором работает дашборд.

## Зависимости

```bash
pip install requests beautifulsoup4 lxml pandas openpyxl tqdm geopy pymorphy3
```

## Этические аспекты

Парсеры обращаются к публично доступным страницам и недокументированным,
но открытым эндпоинтам сайта mir-kvestov.ru. Между запросами выдерживается
задержка 1.2–1.5 сек., чтобы не создавать аномальной нагрузки. Извлекаемая
информация (названия, цены, рейтинги, тексты отзывов) не относится к
конфиденциальной. При публикации результатов исследования агрегированные
данные представляются в обезличенном виде: анализируются распределения,
корреляции и кластеры, а не характеристики отдельных квест-комнат.
