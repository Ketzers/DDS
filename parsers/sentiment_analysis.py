"""
sentiment_analysis.py — словарный анализ тональности отзывов на квест-комнаты.

Алгоритм:
    1. Текст приводится к нижнему регистру и токенизируется.
    2. Каждый токен лемматизируется (pymorphy3) — приводится к нормальной форме.
    3. Лемма ищется в словарях позитивных и негативных слов с весами.
    4. Контекст: для каждого найденного маркера в окне предыдущих слов
       проверяются отрицания («не», «нет»), усилители («очень», «супер»)
       и ослабители («слегка», «немного»).
    5. Сырая оценка = сумма взвешенных вкладов; нормализуется в [-1; +1].
    6. Категория: strongly_positive / positive / neutral / negative / strongly_negative
       по порогам ±0.1 и ±0.5.

Словари адаптированы под доменную область развлечений и квест-комнат:
    - «страшно», «напряжённо», «адреналин» — позитивные маркеры (для хорроров плюс).
    - «скучно», «банально», «предсказуемо» — всегда негативные.

Запуск:
    python sentiment_analysis.py
    # или программно:
    from sentiment_analysis import analyze_all
    analyze_all()

Зависимости:
    pip install pymorphy3 pandas openpyxl tqdm
"""

import re
import pandas as pd

try:
    import pymorphy3
    MORPH = pymorphy3.MorphAnalyzer()
    USE_PYMORPHY = True
except ImportError:
    MORPH = None
    USE_PYMORPHY = False
    print("Предупреждение: pymorphy3 не установлен — лемматизация отключена.")
    print("Установить: pip install pymorphy3")


# ─────────────────────────────────────────────────────────────────────────────
# СЛОВАРИ ПОЗИТИВНОЙ И НЕГАТИВНОЙ ЛЕКСИКИ
# Веса: 2 — сильное чувство, 1 — умеренное, 0 — нейтральное вне контекста.
# ─────────────────────────────────────────────────────────────────────────────

POSITIVE_WORDS = {
    # Сильные положительные эмоции
    'отличный': 2, 'отлично': 2, 'отличная': 2, 'отличное': 2, 'отличные': 2,
    'прекрасный': 2, 'прекрасно': 2, 'прекрасная': 2,
    'превосходный': 2, 'превосходно': 2,
    'восхитительный': 2, 'восхитительно': 2, 'восхитительная': 2,
    'шикарный': 2, 'шикарно': 2, 'шикарная': 2,
    'великолепный': 2, 'великолепно': 2, 'великолепная': 2,
    'идеальный': 2, 'идеально': 2, 'идеальная': 2,
    'потрясающий': 2, 'потрясающе': 2, 'потрясающая': 2,
    'фантастический': 2, 'фантастика': 2, 'фантастически': 2,
    'супер': 2, 'круто': 2, 'класс': 2, 'классный': 2, 'классно': 2,
    'шедевр': 2, 'бомба': 2, 'огонь': 2, 'топ': 2, 'топовый': 2,
    'лучший': 2, 'лучшая': 2, 'лучшее': 2,
    'безупречный': 2, 'безупречно': 2,

    # Умеренные положительные оценки
    'хороший': 1, 'хорошо': 1, 'хорошая': 1, 'хорошее': 1, 'хорошие': 1,
    'понравиться': 1, 'понравилось': 1, 'понравился': 1, 'нравиться': 1,
    'рекомендовать': 1, 'рекомендую': 1, 'рекомендуем': 1,
    'советовать': 1, 'советую': 1, 'советуем': 1,
    'крутой': 1, 'крутая': 1, 'крутое': 1, 'крутые': 1,
    'интересный': 1, 'интересно': 1, 'интересная': 1, 'интересное': 1,
    'увлекательный': 1, 'увлекательно': 1,
    'захватывающий': 1, 'захватывающе': 1,
    'впечатляющий': 1, 'впечатлять': 1, 'впечатлил': 1, 'впечатлило': 1,
    'приятный': 1, 'приятно': 1, 'приятная': 1,
    'душевный': 1, 'душевно': 1,
    'позитивный': 1, 'позитивно': 1, 'позитив': 1,
    'доволен': 1, 'довольный': 1, 'довольна': 1, 'довольны': 1,
    'восторг': 2, 'восторженный': 2,
    'эмоция': 1, 'эмоции': 1, 'эмоциональный': 1,
    'атмосферный': 1, 'атмосфера': 1,
    'продуманный': 1, 'продуманно': 1,
    'качественный': 1, 'качественно': 1,
    'проработанный': 1, 'проработка': 1,
    'молодец': 1, 'молодцы': 1, 'умница': 1,
    'благодарность': 1, 'благодарить': 1, 'спасибо': 1,
    'рад': 1, 'радость': 1, 'радоваться': 1,
    'любимый': 1, 'любить': 1, 'обожать': 1,
    'незабываемый': 2, 'незабываемо': 2,
    'волшебный': 1, 'волшебно': 1, 'волшебство': 1,
    'удивительный': 1, 'удивительно': 1,
    'талантливый': 1, 'талант': 1,
    'профессиональный': 1, 'профессионал': 1, 'профессионально': 1,

    # Доменно-специфичная лексика: для хорроров «страшно» — это похвала
    'страшный': 1, 'страшно': 1, 'жутко': 1, 'жуткий': 1,
    'пугать': 1, 'пугающий': 1, 'пугающе': 1,
    'напряжённый': 1, 'напряжение': 1, 'напряжённо': 1,
    'адреналин': 1, 'мурашки': 1,
}


NEGATIVE_WORDS = {
    # Сильные негативные оценки
    'ужасный': -2, 'ужасно': -2, 'ужасная': -2, 'ужас': -1,
    'отвратительный': -2, 'отвратительно': -2, 'отвратительная': -2,
    'кошмарный': -2, 'кошмарно': -2, 'кошмар': -1,
    'мерзкий': -2, 'мерзко': -2,
    'тупой': -2, 'тупо': -2, 'тупая': -2,
    'бред': -2, 'бредовый': -2,
    'провал': -2, 'провальный': -2,
    'безобразный': -2, 'безобразие': -2,

    # Умеренные негативные оценки
    'плохой': -1, 'плохо': -1, 'плохая': -1, 'плохое': -1,
    'скучный': -1, 'скучно': -1, 'скукота': -1,
    'разочарование': -2, 'разочаровать': -2, 'разочарованы': -2, 'разочаровал': -2,
    'грустный': -1, 'грустно': -1,
    'ожидать': -1, 'ожидали': -1,
    'недоработанный': -1, 'недоработка': -1, 'недоработки': -1,
    'проблема': -1, 'проблемный': -1, 'проблемы': -1,
    'дешёвый': -1, 'дёшево': -1, 'дешевка': -1,
    'примитивный': -1, 'примитивно': -1,
    'банальный': -1, 'банально': -1,
    'очевидный': -1, 'очевидно': -1, 'предсказуемый': -1, 'предсказуемо': -1,
    'непонятный': -1, 'непонятно': -1, 'запутанный': -1,
    'сломанный': -1, 'сломаться': -1, 'поломка': -1, 'поломки': -1,
    'грязный': -1, 'грязно': -1, 'грязь': -1,
    'старый': -1, 'устаревший': -1, 'устарел': -1,
    'халтура': -2, 'халтурный': -2, 'халтурно': -2,
    'фигня': -1, 'ерунда': -1, 'чушь': -1,
    'жаль': -1, 'жалко': -1,
    'пожалеть': -1, 'пожалели': -1,
    'обман': -2, 'обмануть': -2, 'обманули': -2, 'развод': -2,
    'трата': -1, 'потратить': -1, 'впустую': -2,
    'неприятный': -1, 'неприятно': -1,
    'минус': -1, 'минусы': -1, 'недостаток': -1, 'недостатки': -1,
    'дорогой': -1, 'дорого': -1, 'переплата': -1,
    'некомпетентный': -1, 'некомпетентно': -1,
    'грубый': -1, 'грубо': -1, 'хамство': -2, 'хам': -2,

    # Нейтральные в контексте хоррор-квестов
    'бояться': 0, 'страх': 0,
}


# Усилители — увеличивают вес последующего маркера
INTENSIFIERS = {
    'очень': 1.5, 'супер': 1.5, 'мега': 1.5, 'невероятно': 1.8,
    'крайне': 1.5, 'чрезвычайно': 1.5, 'необычайно': 1.5,
    'максимально': 1.5, 'абсолютно': 1.5, 'полностью': 1.3,
    'совершенно': 1.4, 'настолько': 1.3, 'действительно': 1.2,
    'реально': 1.2, 'прям': 1.2, 'просто': 1.1,
}

# Ослабители — уменьшают вес последующего маркера
DIMINISHERS = {
    'слегка': 0.5, 'немного': 0.6, 'чуть': 0.5, 'чуточку': 0.5,
    'местами': 0.6, 'иногда': 0.6, 'отчасти': 0.7,
    'довольно': 0.8, 'относительно': 0.7,
}

# Отрицания — переворачивают знак следующего маркера
NEGATIONS = {'не', 'нет', 'ни', 'без', 'никак', 'никогда', 'никакой', 'нельзя'}


def tokenize(text):
    """Разбивает текст на токены с сохранением кириллицы."""
    text = text.lower()
    return re.findall(r'[а-яёa-z]+', text)


def lemmatize(token):
    """Приводит слово к нормальной форме (инфинитив, им. падеж ед. ч.)."""
    if USE_PYMORPHY and MORPH:
        try:
            return MORPH.parse(token)[0].normal_form
        except Exception:
            return token
    return token


def analyze_sentiment(text, window=3):
    """Считает тональность одного отзыва.

    Args:
        text:   текст отзыва
        window: размер окна слева для проверки контекста (отрицаний, усилителей)

    Returns:
        dict с полями score, score_norm, pos_count, neg_count, category,
        pos_words, neg_words, total_tokens; либо None для пустого текста.
    """
    if not text or not isinstance(text, str):
        return None

    tokens = tokenize(text)
    if not tokens:
        return None

    lemmas = [lemmatize(t) for t in tokens]

    score     = 0.0
    pos_count = 0
    neg_count = 0
    pos_words = []
    neg_words = []

    for i, lemma in enumerate(lemmas):
        base_score    = 0
        found_in_dict = None

        if lemma in POSITIVE_WORDS:
            base_score    = POSITIVE_WORDS[lemma]
            found_in_dict = ('pos', lemma)
        elif lemma in NEGATIVE_WORDS:
            base_score    = NEGATIVE_WORDS[lemma]
            found_in_dict = ('neg', lemma)

        if base_score == 0:
            continue

        # Контекст: смотрим окно слов слева на отрицания/усилители/ослабители
        multiplier = 1.0
        negated    = False

        for prev in lemmas[max(0, i - window):i]:
            if prev in NEGATIONS:
                negated = not negated
            elif prev in INTENSIFIERS:
                multiplier *= INTENSIFIERS[prev]
            elif prev in DIMINISHERS:
                multiplier *= DIMINISHERS[prev]

        final_score = base_score * multiplier
        if negated:
            final_score = -final_score
            # При отрицании метка тоже инвертируется
            if found_in_dict[0] == 'pos':
                found_in_dict = ('neg', f'не {found_in_dict[1]}')
            else:
                found_in_dict = ('pos', f'не {found_in_dict[1]}')

        score += final_score
        if final_score > 0:
            pos_count += 1
            pos_words.append(found_in_dict[1])
        elif final_score < 0:
            neg_count += 1
            neg_words.append(found_in_dict[1])

    # Нормализация в [-1; +1] делением на максимально возможный модуль
    total_eval = pos_count + neg_count
    if total_eval == 0:
        score_norm = 0.0
    else:
        score_norm = score / (total_eval * 2)
    score_norm = max(-1.0, min(1.0, score_norm))

    # Категоризация по порогам
    if   score_norm >  0.5: category = 'strongly_positive'
    elif score_norm >  0.1: category = 'positive'
    elif score_norm > -0.1: category = 'neutral'
    elif score_norm > -0.5: category = 'negative'
    else:                   category = 'strongly_negative'

    return {
        'score':        round(score, 2),
        'score_norm':   round(score_norm, 3),
        'pos_count':    pos_count,
        'neg_count':    neg_count,
        'category':     category,
        'pos_words':    ', '.join(pos_words[:10]),
        'neg_words':    ', '.join(neg_words[:10]),
        'total_tokens': len(lemmas),
    }


def analyze_all(input_file='reviews.xlsx',
                output_reviews='reviews_sentiment.xlsx',
                output_quests='quest_sentiment.xlsx'):
    """Прогоняет анализ тональности по всем отзывам и формирует два файла:
    разметку отдельных отзывов и агрегированную сводку по квестам.
    """
    print(f"Чтение {input_file}...")
    df = pd.read_excel(input_file)
    print(f"Всего отзывов: {len(df):,}")

    print("\nАнализ тональности...")
    if not USE_PYMORPHY:
        print("Без лемматизации точность будет ниже. Установите pymorphy3.")

    try:
        from tqdm import tqdm
        it = tqdm(df.iterrows(), total=len(df))
    except ImportError:
        it = df.iterrows()

    results = []
    for _, row in it:
        sent = analyze_sentiment(row['text'])
        if sent:
            results.append({
                'quest_name': row['quest_name'],
                'author':     row.get('author'),
                'date_iso':   row.get('date_iso'),
                'rating':     row.get('rating'),
                'verified':   row.get('verified'),
                'text':       row['text'][:300],
                **sent,
            })

    df_sent = pd.DataFrame(results)
    df_sent.to_excel(output_reviews, index=False)
    print(f"\nSentiment по отзывам сохранён в {output_reviews}")

    # Агрегация на уровень квеста
    agg = df_sent.groupby('quest_name').agg(
        reviews_analyzed=('score_norm', 'count'),
        avg_sentiment=('score_norm', 'mean'),
        avg_rating=('rating', 'mean'),
        pos_share=('category', lambda x: ((x == 'positive') | (x == 'strongly_positive')).mean()),
        neg_share=('category', lambda x: ((x == 'negative') | (x == 'strongly_negative')).mean()),
        strong_pos=('category', lambda x: (x == 'strongly_positive').sum()),
        strong_neg=('category', lambda x: (x == 'strongly_negative').sum()),
    ).round(3).reset_index()
    agg = agg.sort_values('avg_sentiment', ascending=False)
    agg.to_excel(output_quests, index=False)
    print(f"Sentiment по квестам сохранён в {output_quests}")

    # Печать сводной статистики
    print(f"\n{'=' * 60}")
    print("ОБЩАЯ СТАТИСТИКА")
    print('=' * 60)
    print(f"Проанализировано отзывов: {len(df_sent):,}")
    print(f"Средний sentiment score:  {df_sent['score_norm'].mean():+.3f}")
    print(f"Медианный sentiment:      {df_sent['score_norm'].median():+.3f}")
    print()
    print("Распределение по категориям:")
    for cat, cnt in df_sent['category'].value_counts().items():
        pct = cnt / len(df_sent) * 100
        print(f"  {cat:<20} {cnt:>5} ({pct:>5.1f}%)")

    print(f"\n{'=' * 60}")
    print("ТОП-10 КВЕСТОВ ПО ТОНАЛЬНОСТИ")
    print('=' * 60)
    print(agg.head(10)[['quest_name', 'reviews_analyzed', 'avg_sentiment',
                         'avg_rating', 'pos_share']].to_string(index=False))

    print(f"\n{'=' * 60}")
    print("НИЖНИЕ 10 КВЕСТОВ ПО ТОНАЛЬНОСТИ")
    print('=' * 60)
    print(agg.tail(10)[['quest_name', 'reviews_analyzed', 'avg_sentiment',
                         'avg_rating', 'neg_share']].to_string(index=False))


if __name__ == '__main__':
    analyze_all()
