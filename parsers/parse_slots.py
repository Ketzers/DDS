"""
parse_slots.py — парсер расписания слотов бронирования с сайта mir-kvestov.ru.

Скрипт обращается к внутреннему эндпоинту /time_slots.js, который сайт
использует для отрисовки виджета расписания. В ответ приходит HTML с
кнопками <button data-order-slot="...">, где в data-атрибуте лежит
JSON со всеми параметрами слота: дата, время, цена, скидка. По CSS-классам
элемента определяется статус слота: «free» — свободен, «booked» — занят.

На выходе по каждому квесту имеется длинная таблица слотов за период
наблюдения. Эмпирическая заполняемость считается как доля занятых слотов
от общего числа предложенных.

Запуск:
    python parse_slots.py

Зависимости:
    pip install requests pandas openpyxl
"""

import re
import json
import time
import requests
import pandas as pd


BASE_URL = "https://mir-kvestov.ru"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://mir-kvestov.ru/',
}

DELAY_BETWEEN_REQUESTS = 1.5


def parse_timetable(quest_url_slug):
    """Загружает расписание для одного квеста и возвращает список слотов.

    Args:
        quest_url_slug: последняя часть URL квеста (например, 'circusfamily-kukla')

    Returns:
        список словарей со слотами; пустой список при ошибке.
    """
    api_url = f"{BASE_URL}/time_slots.js?quest_url={quest_url_slug}"

    try:
        response = requests.get(api_url, headers=HEADERS, timeout=30)
        if response.status_code != 200:
            return []
        content = response.text

        # Каждый слот — это <button data-order-slot="{...JSON...}" class="...">время</button>
        button_pattern = re.compile(
            r'<button[^>]*data-order-slot="([^"]*)"[^>]*class="([^"]*)"[^>]*>([^<]*)</button>'
        )

        slots = []
        for match in button_pattern.finditer(content):
            slot_json_escaped = match.group(1)
            css_classes       = match.group(2)
            time_text         = match.group(3).strip()

            # HTML-сущности → нормальные символы перед парсингом JSON
            slot_json = slot_json_escaped.replace('&quot;', '"').replace('&amp;', '&')

            try:
                slot_data = json.loads(slot_json)
            except json.JSONDecodeError:
                continue

            # Статус слота определяется по CSS-классу кнопки
            if   'free'   in css_classes: status = 'свободен'
            elif 'booked' in css_classes: status = 'занят'
            else:                         status = 'неизвестно'

            slots.append({
                'дата':           slot_data.get('date', ''),
                'время':          time_text,
                'цена':           slot_data.get('price', ''),
                'полная_цена':    slot_data.get('full_price', ''),
                'скидка':         slot_data.get('discount', 0),
                'статус':         status,
                'quest_time_id':  slot_data.get('quest_time_id', ''),
            })

        return slots

    except Exception as e:
        print(f"    Ошибка при парсинге расписания {quest_url_slug}: {e}")
        return []


def main(input_file='mir_kvestov_full.xlsx', output_file='slots.xlsx'):
    """Обходит все квесты из входного датасета и собирает их расписания."""
    df = pd.read_excel(input_file)
    print(f"Загружено квестов: {len(df)}")

    all_slots = []

    for i, row in df.iterrows():
        url  = row.get('URL') or row.get('url') or ''
        name = row.get('Название') or row.get('название') or ''
        if not url:
            continue

        # Извлекаем slug — последний сегмент URL
        slug = url.rstrip('/').split('/')[-1]
        print(f"[{i + 1}/{len(df)}] {name[:40]:<40} ({slug})", end='  ')

        slots = parse_timetable(slug)
        print(f"слотов: {len(slots)}")

        for slot in slots:
            slot['квест_url']      = url
            slot['квест_название'] = name
            all_slots.append(slot)

        time.sleep(DELAY_BETWEEN_REQUESTS)

    df_slots = pd.DataFrame(all_slots)
    df_slots.to_excel(output_file, index=False)

    print(f"\n{'=' * 60}")
    print(f"Сохранено слотов: {len(df_slots):,}")
    print(f"Результат: {output_file}")

    if not df_slots.empty:
        free_share = (df_slots['статус'] == 'свободен').mean()
        booked_share = (df_slots['статус'] == 'занят').mean()
        print(f"\nДоля свободных слотов: {free_share:.1%}")
        print(f"Доля занятых слотов:   {booked_share:.1%}")

        print("\nЗаполняемость по квестам (топ-10 и нижние 10):")
        agg = (df_slots.groupby('квест_название')['статус']
               .apply(lambda x: (x == 'занят').mean())
               .sort_values(ascending=False))
        print("\nТоп-10 загруженных:")
        print(agg.head(10).to_string())
        print("\nНижние 10:")
        print(agg.tail(10).to_string())


if __name__ == '__main__':
    main()
