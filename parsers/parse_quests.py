"""
parse_quests.py — парсер каталога квест-комнат с сайта mir-kvestov.ru.

Скрипт работает в две стадии:
    1. Сбор ссылок с каталога /quests/search (отсортированных по рейтингу).
    2. Обход каждой страницы квеста и извлечение всех атрибутов карточки.

Извлекаемые поля:
    - название, тип, время прохождения, число игроков, цена, сложность,
    - уровень страха, возрастное ограничение, народный рейтинг, число команд,
    - метро, адрес, телефон, организатор, оснащение, категории, описание.

Запуск:
    python parse_quests.py

Зависимости:
    pip install requests beautifulsoup4 lxml pandas openpyxl
"""

import re
import json
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd


BASE_URL   = "https://mir-kvestov.ru"
SEARCH_URL = f"{BASE_URL}/quests/search"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://mir-kvestov.ru/',
}

DELAY_BETWEEN_REQUESTS = 1.5  # сек., чтобы не нагружать сайт


# ─────────────────────────────────────────────────────────────────────────────
# СБОР ССЫЛОК НА КВЕСТЫ С КАТАЛОГА
# ─────────────────────────────────────────────────────────────────────────────

def get_quest_links_from_page(page_num):
    """Возвращает список ссылок на квесты с одной страницы каталога
    и общее число страниц."""
    params = {'sort': 'rating', 'city': 'msk', 'page': page_num}

    try:
        response = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        if response.status_code != 200:
            print(f"  Ошибка: статус {response.status_code}")
            return [], 0

        soup = BeautifulSoup(response.text, 'lxml')

        # Максимальное число страниц каталога (атрибут кнопки «Показать ещё»)
        max_page = 0
        load_more = soup.find(id='search-load-more')
        if load_more:
            max_page = int(load_more.get('data-max-page', 0))

        # Извлечение ссылок на карточки квестов
        quest_links = []
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            if ('/quests/' in href
                    and '#' not in href
                    and 'search' not in href
                    and 'balachiha' not in href     # фильтр Балашихи (другой регион)
                    and href not in seen):
                seen.add(href)
                full_url = BASE_URL + href if href.startswith('/') else href
                quest_links.append(full_url)

        return quest_links, max_page
    except Exception as e:
        print(f"  Ошибка при загрузке страницы {page_num}: {e}")
        return [], 0


def get_top_quest_links(target=300, max_pages=15):
    """Собирает уникальные ссылки на топ-квесты, обходя страницы каталога."""
    all_links = []
    print(f"Сбор ссылок на топ-{target} квестов...")

    for page in range(1, max_pages + 1):
        links, max_page = get_quest_links_from_page(page)
        print(f"  Страница {page}: найдено {len(links)} (всего страниц: {max_page})")

        for link in links:
            if link not in all_links:
                all_links.append(link)

        if len(all_links) >= target:
            break
        time.sleep(DELAY_BETWEEN_REQUESTS)

    return all_links[:target]


# ─────────────────────────────────────────────────────────────────────────────
# ПАРСИНГ ОТДЕЛЬНОЙ СТРАНИЦЫ КВЕСТА
# ─────────────────────────────────────────────────────────────────────────────

def parse_quest_detail(url):
    """Извлекает все атрибуты квеста с его страницы.

    Returns:
        dict со всеми полями карточки или None при ошибке.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code != 200:
            print(f"    Ошибка: статус {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'lxml')

        quest_data = {
            'url': url, 'название': '', 'тип_квеста': '',
            'игроков': '', 'время': '', 'цена': '',
            'сложность': '', 'уровень_страха': '', 'возраст': '',
            'народный_рейтинг': '', 'число_команд': '',
            'метро': '', 'адрес': '', 'телефон': '', 'организатор': '',
            'в_квесте_есть': '', 'категории': '', 'описание': '',
        }

        # ── Название ────────────────────────────────────────────────────────
        h1 = soup.find('h1')
        if h1:
            quest_data['название'] = h1.get_text(strip=True)

        # ── Тип квеста ──────────────────────────────────────────────────────
        game_type = soup.find(class_='game-type')
        if game_type:
            quest_data['тип_квеста'] = game_type.get_text(strip=True)

        # ── Параметры из <li class="cell"> ──────────────────────────────────
        # Структура: span.th — подпись, span.td — значение, при наличии
        # tooltip берём подпись из rich-tooltip-1-title.
        for li in soup.find_all('li', class_='cell'):
            label_span = li.find('span', class_='th')
            value_td   = li.find('span', class_='td')
            if not label_span or not value_td:
                continue

            label_text = label_span.get_text(strip=True).lower().rstrip('*')

            tooltip_span = value_td.find(attrs={'data-original-title': True})
            if tooltip_span:
                tooltip_html = tooltip_span.get('data-original-title', '')
                tooltip_soup = BeautifulSoup(tooltip_html, 'lxml')
                title_tag    = tooltip_soup.find(class_='rich-tooltip-1-title')
                value_text   = (title_tag.get_text(strip=True)
                                if title_tag else value_td.get_text(strip=True))
            else:
                value_text = value_td.get_text(strip=True)

            if   'игрок'   in label_text: quest_data['игроков']        = value_text
            elif 'врем'    in label_text: quest_data['время']          = value_text
            elif 'цен'     in label_text: quest_data['цена']           = value_text
            elif 'сложн'   in label_text: quest_data['сложность']      = value_text
            elif 'страх'   in label_text: quest_data['уровень_страха'] = value_text
            elif 'возраст' in label_text: quest_data['возраст']        = value_td.get_text(strip=True)

        # ── Народный рейтинг и число команд ─────────────────────────────────
        rating_figure = soup.find('span', class_='quest-rating-populi__value-figure')
        if rating_figure:
            quest_data['народный_рейтинг'] = rating_figure.get_text(strip=True)

        teams_count = soup.find('span', class_='quest-rating-populi__team-count_number')
        if teams_count:
            quest_data['число_команд'] = teams_count.get_text(strip=True)

        # ── Контактная информация ───────────────────────────────────────────
        contacts = soup.find(class_='contacts')
        if contacts:
            metro_p = contacts.find('p', class_='with-bullet-icon-1')
            if metro_p:
                metro_text = metro_p.get_text(strip=True)
                metro_text = re.sub(r'\(показать карту\)', '', metro_text).strip()
                quest_data['адрес'] = metro_text

            phone_link = contacts.find('a', href=re.compile(r'tel:'))
            if phone_link:
                quest_data['телефон'] = phone_link.get_text(strip=True)

            for p in contacts.find_all('p'):
                text = p.get_text(strip=True)
                if 'оказывает' in text.lower():
                    quest_data['организатор'] = text
                    break

        # ── Метро (отдельным полем — выделяем из адреса) ────────────────────
        if 'м.' in quest_data.get('адрес', ''):
            metro_match = re.search(r'м\.\s*([^,]+)', quest_data['адрес'])
            if metro_match:
                quest_data['метро'] = 'м. ' + metro_match.group(1).strip()

        # ── Оснащение («В квесте есть») ─────────────────────────────────────
        commodities = soup.find(class_='commodities')
        if commodities:
            items = [p.get_text(strip=True) for p in commodities.find_all('p')
                     if p.get_text(strip=True)]
            quest_data['в_квесте_есть'] = ' | '.join(items)

        # ── Категории (теги) ────────────────────────────────────────────────
        tags_block = soup.find(class_='tags')
        if tags_block:
            h3 = tags_block.find('h3')
            if h3:
                h3.decompose()
            tags = [a.get_text(strip=True) for a in tags_block.find_all('a')]
            if not tags:
                tags = [li.get_text(strip=True) for li in tags_block.find_all('li')]
            quest_data['категории'] = (', '.join(tags) if tags
                                       else tags_block.get_text(strip=True))

        # ── Описание ────────────────────────────────────────────────────────
        desc = soup.find(class_='annotation')
        if desc:
            quest_data['описание'] = desc.get_text(strip=True)[:500]

        return quest_data

    except Exception as e:
        print(f"    Ошибка при парсинге {url}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ОСНОВНОЙ ПАЙПЛАЙН
# ─────────────────────────────────────────────────────────────────────────────

def main(target=100,
         output_links='top_links.json',
         output_xlsx='quests_data.xlsx'):
    """Полный цикл: каталог → ссылки → карточки → Excel."""
    print("=" * 60)
    print("Шаг 1. Сбор ссылок на квесты")
    print("=" * 60)
    quest_links = get_top_quest_links(target=target)
    print(f"\nВсего собрано ссылок: {len(quest_links)}")

    with open(output_links, 'w', encoding='utf-8') as f:
        json.dump(quest_links, f, ensure_ascii=False, indent=2)
    print(f"Список ссылок сохранён в {output_links}")

    print("\n" + "=" * 60)
    print("Шаг 2. Парсинг карточек квестов")
    print("=" * 60)

    all_quests = []
    for i, url in enumerate(quest_links, 1):
        print(f"\n[{i}/{len(quest_links)}] {url}")
        quest_data = parse_quest_detail(url)
        if quest_data:
            quest_data['номер'] = i
            all_quests.append(quest_data)
            print(f"    {quest_data['название']}")
            print(f"    {quest_data['игроков']} | {quest_data['время']} | {quest_data['цена']}")
        time.sleep(DELAY_BETWEEN_REQUESTS)

    df = pd.DataFrame(all_quests)
    df.to_excel(output_xlsx, index=False)

    print(f"\n{'=' * 60}")
    print(f"Готово. Собрано квестов: {len(all_quests)}")
    print(f"Результат: {output_xlsx}")
    print("=" * 60)


if __name__ == '__main__':
    main()
