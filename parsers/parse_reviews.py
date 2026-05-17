"""
parse_reviews.py — парсер отзывов с сайта mir-kvestov.ru.

Со страницы каждого квеста извлекаются:
    1. Стандартные отзывы в блоках <div class="review-1"> (до 25 на квест,
       видимы без подгрузки через AJAX).
    2. Избранные отзывы <div class="featured-review"> (1–2 шт. на квест).
    3. Сводная информация: общее число отзывов, распределение рейтингов.

Поля каждого отзыва: автор, дата, рейтинг, текст, ответ организатора,
флаг «верифицирован», признак квест-мастера.

Полный список всех отзывов подгружается у сайта Vue-приложением через
внутренний AJAX-эндпоинт, недоступный обычному HTTP-клиенту. Для целей
анализа тональности 25 отзывов на квест достаточно.

Запуск:
    python parse_reviews.py
    # или с программным импортом:
    from parse_reviews import main
    main(limit=3)        # тест на трёх квестах
    main()               # все квесты из mir_kvestov_full.xlsx

Зависимости:
    pip install requests beautifulsoup4 lxml pandas openpyxl tqdm
"""

import re
import json
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
    'Referer': 'https://mir-kvestov.ru/',
}

DELAY_BETWEEN_REQUESTS = 1.2  # сек., чтобы не нагружать сайт


def parse_review_1(div):
    """Парсит отзыв в формате <div class="review-1">."""
    review = {}

    rating_p = div.find('p', class_='rating')
    if rating_p and rating_p.get('data-rating'):
        try:
            review['rating'] = int(rating_p['data-rating'])
        except (ValueError, TypeError):
            review['rating'] = len(rating_p.find_all('i', class_='fa-star'))
    else:
        review['rating'] = None
    review['max_rating'] = 5

    time_tag = div.find('time')
    if time_tag:
        review['date_iso']   = time_tag.get('datetime', '')[:10]
        review['date_human'] = time_tag.get_text(strip=True)
    else:
        review['date_iso']   = ''
        review['date_human'] = ''

    comment = div.find('p', class_='review-comment')
    if comment:
        text = comment.get_text(' ', strip=True)
        review['text'] = re.sub(r'\s+', ' ', text)
    else:
        review['text'] = ''

    quest_comment = div.find('p', class_='quest-comment')
    if quest_comment:
        qc_text = quest_comment.get_text(' ', strip=True)
        qc_text = re.sub(r'^Комментарий квеста:\s*', '', qc_text)
        review['organizer_reply'] = re.sub(r'\s+', ' ', qc_text)
    else:
        review['organizer_reply'] = ''

    cite = div.find('cite')
    if cite:
        b = cite.find('b')
        review['author'] = b.get_text(strip=True) if b else ''
        cite_text = cite.get_text(' ', strip=True)
        exp_match = re.search(r'\(([^)]+)\)', cite_text)
        review['experience']   = exp_match.group(1) if exp_match else ''
        review['quest_master'] = bool(cite.find('span', class_='genius'))
    else:
        review['author']       = ''
        review['experience']   = ''
        review['quest_master'] = False

    review['verified'] = 'verified' in div.get('class', [])
    return review


def parse_featured_review(div):
    """Парсит избранный отзыв <div class="featured-review">."""
    review = {'verified': False, 'quest_master': False, 'organizer_reply': ''}

    rating_el = div.find(attrs={'data-rating': True})
    if rating_el:
        try:
            review['rating'] = int(rating_el['data-rating'])
        except (ValueError, TypeError):
            review['rating'] = None
    else:
        stars = div.find_all('i', class_='fa-star')
        review['rating'] = len(stars) if stars else None
    review['max_rating'] = 5

    time_tag = div.find('time')
    review['date_iso']   = time_tag.get('datetime', '')[:10] if time_tag else ''
    review['date_human'] = time_tag.get_text(strip=True) if time_tag else ''

    quote = div.find(['blockquote', 'p'], class_=re.compile(r'comment|text|quote'))
    if quote:
        text = quote.get_text(' ', strip=True)
        review['text'] = re.sub(r'\s+', ' ', text)
    else:
        all_text = div.get_text(' ', strip=True)
        review['text'] = re.sub(r'\s+', ' ', all_text)[:500]

    cite = div.find('cite') or div.find(class_=re.compile(r'author'))
    review['author']     = cite.get_text(' ', strip=True)[:80] if cite else ''
    review['experience'] = ''
    return review


def extract_quest_meta(soup):
    """Извлекает сводные данные: общее число отзывов и распределение рейтингов."""
    info = {'total_reviews': None, 'verified_reviews': None,
            'quest_id': None, 'rating_distribution': None}

    meta = soup.find('meta', {'name': 'reviews-data'})
    if meta:
        try:
            data = json.loads(meta.get('content', '{}'))
            info['quest_id']            = data.get('quest_id')
            info['rating_distribution'] = data.get('cohorts')
        except json.JSONDecodeError:
            pass

    for h2 in soup.find_all(['h2', 'h3']):
        text = h2.get_text(' ', strip=True)
        m_total = re.search(r'(\d+)\s*отзыв', text)
        if m_total:
            info['total_reviews'] = int(m_total.group(1))
        m_verified = re.search(r'(\d+)\s*проверенн', text)
        if m_verified:
            info['verified_reviews'] = int(m_verified.group(1))
        if info['total_reviews']:
            break

    return info


def parse_reviews_for_quest(quest_url, quest_name):
    """Скачивает страницу квеста и извлекает с неё отзывы и метаданные."""
    try:
        resp = requests.get(quest_url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return [], {'error': f'HTTP {resp.status_code}'}
    except requests.RequestException as e:
        return [], {'error': str(e)}

    soup = BeautifulSoup(resp.text, 'lxml')
    meta = extract_quest_meta(soup)
    reviews = []

    for div in soup.find_all('div', class_='review-1'):
        rev = parse_review_1(div)
        if rev.get('text'):
            rev['quest_name'] = quest_name
            rev['quest_url']  = quest_url
            rev['source']     = 'review-1'
            reviews.append(rev)

    for div in soup.find_all('div', class_='featured-review'):
        rev = parse_featured_review(div)
        if rev.get('text') and len(rev['text']) > 20:
            rev['quest_name'] = quest_name
            rev['quest_url']  = quest_url
            rev['source']     = 'featured'
            duplicate = any(
                r['author'] == rev['author']
                and r['date_iso'] == rev['date_iso']
                and r['text'][:50] == rev['text'][:50]
                for r in reviews
            )
            if not duplicate:
                reviews.append(rev)

    return reviews, meta


def main(input_file='mir_kvestov_full.xlsx',
         output_reviews='reviews.xlsx',
         output_stats='reviews_stats.xlsx',
         limit=None):
    """Парсит отзывы для всех квестов из входного датасета.

    Args:
        input_file:     путь к Excel со списком квестов (нужны колонки URL и Название)
        output_reviews: куда сохранить тексты отзывов
        output_stats:   куда сохранить сводную статистику по квестам
        limit:          ограничение числа квестов (None — все)
    """
    df = pd.read_excel(input_file)
    if limit:
        df = df.head(limit)

    all_reviews = []
    stats_rows  = []

    print(f"Парсим отзывы для {len(df)} квестов...")

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Квесты"):
        url  = row.get('URL')      or row.get('url')
        name = row.get('Название') or row.get('название')
        if not url or not name:
            continue

        try:
            reviews, meta = parse_reviews_for_quest(url, name)
            all_reviews.extend(reviews)

            avg_rating = None
            if reviews:
                valid = [r['rating'] for r in reviews if r.get('rating')]
                if valid:
                    avg_rating = round(sum(valid) / len(valid), 2)

            stats_rows.append({
                'quest_name':       name,
                'quest_url':        url,
                'quest_id':         meta.get('quest_id'),
                'total_reviews':    meta.get('total_reviews'),
                'verified_reviews': meta.get('verified_reviews'),
                'collected':        len(reviews),
                'avg_rating':       avg_rating,
                'error':            meta.get('error', ''),
            })

            if meta.get('error'):
                tqdm.write(f"  [{name[:40]:<40}] ОШИБКА: {meta['error']}")
            else:
                total = meta.get('total_reviews', '?')
                tqdm.write(f"  [{name[:40]:<40}] на сайте: {str(total):>4}, собрано: {len(reviews):>3}")

        except Exception as e:
            tqdm.write(f"  [{name[:40]:<40}] ИСКЛЮЧЕНИЕ: {e}")
            stats_rows.append({
                'quest_name': name, 'quest_url': url, 'collected': 0,
                'error': str(e)[:200],
            })

        time.sleep(DELAY_BETWEEN_REQUESTS)

    if not all_reviews:
        print("\nНе удалось собрать ни одного отзыва.")
        return

    df_rev = pd.DataFrame(all_reviews)
    cols = ['quest_name', 'quest_url', 'date_iso', 'date_human',
            'author', 'experience', 'rating', 'max_rating',
            'verified', 'quest_master', 'text', 'organizer_reply', 'source']
    df_rev = df_rev[[c for c in cols if c in df_rev.columns]]
    df_rev.to_excel(output_reviews, index=False)

    df_stats = pd.DataFrame(stats_rows)
    df_stats.to_excel(output_stats, index=False)

    print(f"\n{'=' * 60}")
    print(f"Сохранено {len(df_rev):,} отзывов в {output_reviews}")
    print(f"Статистика по {len(df_stats)} квестам в {output_stats}")
    print(f"Квестов с отзывами: {df_rev['quest_name'].nunique()}/{len(df_stats)}")
    print(f"Средняя длина отзыва: {df_rev['text'].str.len().mean():.0f} символов")
    print(f"Доля верифицированных: {df_rev['verified'].mean():.0%}")
    print(f"\nРаспределение рейтингов:")
    for r, c in df_rev['rating'].value_counts().sort_index().items():
        print(f"  {r} звёзд: {c:,} ({c / len(df_rev):.0%})")


if __name__ == '__main__':
    main()
