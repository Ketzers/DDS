

import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st



ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sppr import load_survey_metrics


st.set_page_config(
    page_title="СППР: квест-комнаты Москвы",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown("""
<style>
    /* Шапка лендинга */
    .landing-header {
        padding: 24px 0 8px 0;
    }
    .landing-title {
        font-size: 2.4rem; font-weight: 700; color: #111827;
        line-height: 1.15; margin-bottom: 4px;
    }
    .landing-subtitle {
        font-size: 1.1rem; color: #6b7280; max-width: 800px;
    }

    /* Карточки навигации */
    .nav-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 24px;
        height: 100%;
        transition: box-shadow 0.15s ease, border-color 0.15s ease;
        border-top: 4px solid;
    }
    .nav-card:hover {
        border-color: #cbd5e1;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
    }
    .nav-card-1 { border-top-color: #1e3a8a; }   /* Изучить рынок — синий */
    .nav-card-2 { border-top-color: #16a34a; }   /* Оценить проект — зелёный */
    .nav-card-3 { border-top-color: #ca8a04; }   /* Сравнить — янтарный */

    .nav-card-label {
        font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em;
        color: #6b7280; font-weight: 600;
    }
    .nav-card-title {
        font-size: 1.4rem; font-weight: 700; color: #111827;
        margin: 6px 0 10px 0;
    }
    .nav-card-desc {
        font-size: 0.95rem; color: #374151; line-height: 1.5;
        min-height: 90px;
    }
    .nav-card-meta {
        font-size: 0.85rem; color: #6b7280;
        margin-top: 12px; padding-top: 12px;
        border-top: 1px solid #f3f4f6;
    }

    /* Блок «О данных» */
    .data-block {
        background: #f9fafb;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 20px 24px;
    }
    .data-stat {
        font-size: 1.6rem; font-weight: 700; color: #111827;
        font-variant-numeric: tabular-nums;
    }
    .data-stat-label {
        font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em;
        color: #6b7280; margin-top: 2px;
    }

    /* Шаги «Как пользоваться» */
    .step-num {
        display: inline-block;
        width: 28px; height: 28px; line-height: 28px;
        text-align: center;
        background: #1e3a8a; color: #ffffff;
        border-radius: 50%; font-weight: 700; font-size: 0.9rem;
        margin-right: 10px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def _load_meta():
    quests_path  = os.path.join(ROOT, 'mir_kvestov_full.xlsx')
    reviews_path = os.path.join(ROOT, 'reviews_sentiment.xlsx')

    n_quests = 0
    n_reviews = 0
    quests_mtime = None

    try:
        df = pd.read_excel(quests_path)
        n_quests = len(df)
        quests_mtime = os.path.getmtime(quests_path)
    except FileNotFoundError:
        pass

    try:
        rev = pd.read_excel(reviews_path)
        n_reviews = len(rev)
    except FileNotFoundError:
        pass

    return n_quests, n_reviews, quests_mtime


n_quests, n_reviews, quests_mtime = _load_meta()
survey = load_survey_metrics(os.path.join(ROOT, 'survey.xlsx'))

data_timestamp = (datetime.fromtimestamp(quests_mtime).strftime('%d.%m.%Y')
                  if quests_mtime else 'неизвестно')


st.markdown("""
<div class="landing-header">
    <div class="landing-title">Система поддержки принятия решений</div>
    <div class="landing-subtitle">
        Аналитический инструмент для оценки инвестиционной привлекательности
        нового квест-проекта на московском рынке. На основе данных о
        конкурентах, опроса целевой аудитории и финансовой модели — выдаёт
        прозрачную оценку и рекомендации по улучшению.
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("")




# Проверяем наличие st.switch_page 
HAS_SWITCH_PAGE = hasattr(st, 'switch_page')

col1, col2, col3 = st.columns(3)


with col1:
    st.markdown("""
    <div class="nav-card nav-card-1">
        <div class="nav-card-label">01 — Контекст</div>
        <div class="nav-card-title">Изучить рынок</div>
        <div class="nav-card-desc">
            Карта конкурентов с тепловой плотностью и кластерами по DBSCAN,
            аналитика по структуре, ценам и тональности отзывов.
            Поможет сформулировать гипотезу проекта.
        </div>
        <div class="nav-card-meta">
            100 квест-комнат · 250+ станций метро · сезонность 6 месяцев
        </div>
    </div>
    """, unsafe_allow_html=True)
    if HAS_SWITCH_PAGE:
        if st.button("Перейти к изучению рынка", key="go_market",
                     use_container_width=True, type="primary"):
            st.switch_page("pages/00_Explore_market.py")
    else:
        st.caption("Откройте «00 Explore market» в боковом меню")

# Оценить мой проект 
with col2:
    st.markdown("""
    <div class="nav-card nav-card-2">
        <div class="nav-card-label">02 — Оценка</div>
        <div class="nav-card-title">Оценить мой проект</div>
        <div class="nav-card-desc">
            Введите параметры проекта (локация, формат, цена, бюджет) —
            система рассчитает оценку по 4 критериям, выдаст вердикт
            и предложит стратегии улучшения с пересчётом метрик.
        </div>
        <div class="nav-card-meta">
            4 критерия · радар-диаграмма · комбинированные стратегии
        </div>
    </div>
    """, unsafe_allow_html=True)
    if HAS_SWITCH_PAGE:
        if st.button("Перейти к оценке проекта", key="go_evaluate",
                     use_container_width=True, type="primary"):
            st.switch_page("pages/01_Evaluate_project.py")
    else:
        st.caption("Откройте «01 Evaluate project» в боковом меню")

#  Сравнить варианты
with col3:
    n_saved = len(st.session_state.get('saved_projects', []))
    saved_meta = (f"В корзине: {n_saved} вариант(ов)" if n_saved > 0
                  else "Сохраните проекты на странице оценки")
    st.markdown(f"""
    <div class="nav-card nav-card-3">
        <div class="nav-card-label">03 — Выбор</div>
        <div class="nav-card-title">Сравнить варианты</div>
        <div class="nav-card-desc">
            Сопоставьте несколько оценённых проектов рядом — таблица
            параметров, наложенные радары, столбчатая диаграмма скоров,
            автоматический разбор сильных и слабых сторон.
        </div>
        <div class="nav-card-meta">
            {saved_meta}
        </div>
    </div>
    """, unsafe_allow_html=True)
    if HAS_SWITCH_PAGE:
        if st.button("Перейти к сравнению", key="go_compare",
                     use_container_width=True, type="primary",
                     disabled=(n_saved == 0)):
            st.switch_page("pages/02_Compare_projects.py")
    else:
        st.caption("Откройте «02 Compare projects» в боковом меню")


st.markdown("")
st.markdown("---")


st.markdown("### О данных")

data_col1, data_col2, data_col3, data_col4 = st.columns(4)

with data_col1:
    st.markdown(f"""
    <div class="data-block">
        <div class="data-stat">{n_quests}</div>
        <div class="data-stat-label">квест-комнат</div>
        <div style="margin-top:8px;font-size:0.85rem;color:#6b7280">
            Источник: Мир Квестов
        </div>
    </div>
    """, unsafe_allow_html=True)

with data_col2:
    st.markdown(f"""
    <div class="data-block">
        <div class="data-stat">{n_reviews:,}</div>
        <div class="data-stat-label">отзывов</div>
        <div style="margin-top:8px;font-size:0.85rem;color:#6b7280">
            С тональным анализом (pymorphy3)
        </div>
    </div>
    """, unsafe_allow_html=True)

with data_col3:
    st.markdown(f"""
    <div class="data-block">
        <div class="data-stat">{survey.n_respondents}</div>
        <div class="data-stat-label">респондентов опроса</div>
        <div style="margin-top:8px;font-size:0.85rem;color:#6b7280">
            Целевая аудитория квест-комнат Москвы
        </div>
    </div>
    """, unsafe_allow_html=True)

with data_col4:
    st.markdown(f"""
    <div class="data-block">
        <div class="data-stat">{data_timestamp}</div>
        <div class="data-stat-label">данные обновлены</div>
        <div style="margin-top:8px;font-size:0.85rem;color:#6b7280">
            Период наблюдения: окт 2025 – мар 2026
        </div>
    </div>
    """, unsafe_allow_html=True)



st.markdown("")
st.markdown("### Как пользоваться")
st.markdown(
    "Стандартный сценарий — пять шагов от изучения рынка до выбора лучшего варианта:"
)

steps = [
    ("Изучите рынок",
     "Откройте раздел «Изучить рынок», посмотрите карту и аналитику. "
     "Выявите зоны концентрации конкурентов и недопредставленные жанровые ниши."),
    ("Сформулируйте гипотезу проекта",
     "Определите примерные параметры: где (станция метро), что (тип и жанр), "
     "по какой цене, с каким бюджетом."),
    ("Получите оценку",
     "Перейдите в «Оценить мой проект», введите параметры — система выдаст "
     "балл, вердикт и подробный разбор по четырём критериям."),
    ("Изучите рекомендации",
     "Если оценка не зелёная — система предложит стратегии улучшения. "
     "Можно применить рекомендацию и увидеть пересчитанный результат."),
    ("Сохраните и сравните",
     "Сохраните несколько вариантов в корзину сравнения и сопоставьте "
     "их рядом — поможет выбрать наиболее перспективный."),
]

for i, (title, text) in enumerate(steps, 1):
    st.markdown(f"""
    <div style="margin: 12px 0; padding-left: 0">
        <div style="font-weight:600;color:#111827;margin-bottom:4px">
            <span class="step-num">{i}</span>{title}
        </div>
        <div style="color:#374151;padding-left:38px;font-size:0.95rem">{text}</div>
    </div>
    """, unsafe_allow_html=True)



st.markdown("")
st.markdown("---")

with st.expander("Методология и ограничения"):
    st.markdown(f"""
    **Источники данных:**

    - **Конкурентная среда:** парсинг сайта «Мир Квестов» (топ-{n_quests} квестов
      Москвы по рейтингу). Извлекаются координаты, тип, цена, рейтинг, отзывы.
    - **Тональность отзывов:** {n_reviews:,} отзывов проанализированы методом
      словарного подхода с лемматизацией (pymorphy3). Корреляция с звёздным
      рейтингом подтверждает валидность.
    - **Опрос целевой аудитории:** {survey.n_respondents} респондент(ов).
      Извлекаются медианы готовности платить, цена отказа, спрос по жанрам,
      ранги факторов выбора.
    - **Заполняемость:** агрегированные показатели по периоду наблюдения
      окт 2025 – мар 2026 с учётом рейтинга, числа отзывов, дня недели
      и сезонности.

    **Скоринговый движок (4 критерия):**

    - **Конкурентная плотность** (вес 30%): KDE/DBSCAN, радиус 900 м.
    - **Конкурентная среда** (вес 25%): медианная популярность конкурентов
      в радиусе 900 м как прокси для их рыночной зрелости и узнаваемости.
    - **Соответствие цены спросу** (вес 20%): доля принимающей аудитории
      на основе медиан опроса.
    - **Финансовая жизнеспособность** (вес 25%): юнит-экономика на прогнозной
      заполняемости. Окупаемость >36 мес = блокирующий риск.

    **Ограничения:**

    - Топ-{n_quests} — это около 30% московского рынка; полный охват поможет
      точнее оценить «свободные» центральные локации.
    - Коэффициенты аренды по округам — ориентиры из открытых источников
      (ЦИАН/Авито), не точные ставки конкретных помещений.
    """)
