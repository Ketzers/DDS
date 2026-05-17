"""
pages/1_Оценить_проект.py — страница оценки инвестиционного проекта в СППР.

Реализует полный цикл:
    1. Ввод параметров проекта (форма)
    2. Запуск скорингового движка (4 критерия)
    3. Структурированный отчёт (вердикт + критерии + радар + блокеры)
    4. Рекомендации (одиночные + комбинированные стратегии)
    5. Применение стратегии и сравнение «до/после»

Использует пакет sppr/ (см. sppr/scoring.py, sppr/survey_metrics.py, sppr/metro_stations.py).
"""

import os
import sys

import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ── Путь к корню проекта (родительская папка к pages/) ──────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sppr import (
    ProjectInput, evaluate_project,
    suggest_improvements, suggest_combined_strategy,
    load_survey_metrics,
    find_station, get_station_names,
)
from sppr.scoring import add_genre_column, KNOWN_GENRES
from sppr.metro_stations import get_rent_zone


# ── Конфигурация страницы ───────────────────────────────────────────────
st.set_page_config(
    page_title="Оценить проект — СППР",
    page_icon=None,
    layout="wide",
)


# ── CSS для отчётных блоков ─────────────────────────────────────────────
st.markdown("""
<style>
    .verdict-block {
        padding: 24px 28px;
        border-radius: 8px;
        border: 1px solid;
        margin: 16px 0;
    }
    .verdict-green   { background: #f0fdf4; border-color: #16a34a; color: #14532d; }
    .verdict-yellow  { background: #fefce8; border-color: #ca8a04; color: #713f12; }
    .verdict-red     { background: #fef2f2; border-color: #dc2626; color: #7f1d1d; }
    .verdict-score   { font-size: 3rem; font-weight: 700; line-height: 1.1;
                       font-variant-numeric: tabular-nums; }
    .verdict-label   { font-size: 0.85rem; text-transform: uppercase;
                       letter-spacing: 0.05em; opacity: 0.75; }
    .verdict-text    { font-size: 1rem; margin-top: 8px; }

    .criterion-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        padding: 14px 18px;
        margin-bottom: 6px;
        border-left: 4px solid #94a3b8;
    }
    .criterion-card.green   { border-left-color: #16a34a; }
    .criterion-card.yellow  { border-left-color: #ca8a04; }
    .criterion-card.red     { border-left-color: #dc2626; }
    .criterion-name         { font-size: 0.95rem; font-weight: 600; color: #111827; }
    .criterion-score        { font-size: 1.4rem; font-weight: 600;
                              font-variant-numeric: tabular-nums; }

    .strategy-card {
        background: #f9fafb;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        padding: 16px 20px;
        margin-bottom: 8px;
    }
    .strategy-label { font-size: 1rem; font-weight: 600; color: #1f2937; }
    .strategy-summary { font-size: 0.9rem; color: #6b7280; margin: 4px 0 12px 0; }
    .strategy-score { font-size: 1.5rem; font-weight: 700; color: #111827;
                      font-variant-numeric: tabular-nums; }

    .blocker-block {
        background: #fef2f2;
        border: 1px solid #fca5a5;
        border-left: 4px solid #dc2626;
        border-radius: 6px;
        padding: 12px 16px;
        margin: 12px 0;
        color: #7f1d1d;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА ДАННЫХ (с кешем)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data
def _load_quests():
    df = pd.read_excel(os.path.join(ROOT, 'mir_kvestov_full.xlsx'))
    df['Метро_чистое'] = df['Метро'].str.replace('м. ', '', regex=False).str.strip()
    df = add_genre_column(df)
    return df


@st.cache_data
def _load_survey():
    return load_survey_metrics(os.path.join(ROOT, 'survey.xlsx'))


df = _load_quests()
survey = _load_survey()


# ─────────────────────────────────────────────────────────────────────────────
# СОСТОЯНИЕ СТРАНИЦЫ
# ─────────────────────────────────────────────────────────────────────────────
if 'evaluation_done' not in st.session_state:
    st.session_state.evaluation_done = False
if 'current_input' not in st.session_state:
    st.session_state.current_input = None
if 'original_input' not in st.session_state:
    st.session_state.original_input = None
# Корзина сохранённых проектов для страницы «Сравнить варианты»
if 'saved_projects' not in st.session_state:
    st.session_state.saved_projects = []  # list of dict: {name, input, score}


# ─────────────────────────────────────────────────────────────────────────────
# ВЕРХНЯЯ ШАПКА
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("# Оценка инвестиционного проекта")
st.markdown(
    "Введите параметры планируемой квест-комнаты, и система оценит проект "
    "по четырём критериям, выдаст вердикт и предложит стратегии улучшения. "
    "В основе оценки — данные о московском рынке квест-комнат и опрос целевой аудитории."
)

st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# ФОРМА ВВОДА
# ─────────────────────────────────────────────────────────────────────────────

with st.form("project_form", clear_on_submit=False):
    st.markdown("### Параметры проекта")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Локация и формат**")

        station_names = ['(введу координаты вручную)'] + get_station_names()
        default_idx = station_names.index('Бауманская') if 'Бауманская' in station_names else 0
        chosen_station = st.selectbox(
            "Станция метро",
            options=station_names,
            index=default_idx,
            help="Координаты подставятся автоматически. Выберите «(введу координаты вручную)», "
                 "чтобы указать произвольную точку.",
        )

        if chosen_station == '(введу координаты вручную)':
            man_col1, man_col2 = st.columns(2)
            with man_col1:
                lat = st.number_input("Широта (lat)", value=55.7558,
                                       format="%.4f", step=0.001)
            with man_col2:
                lon = st.number_input("Долгота (lon)", value=37.6173,
                                       format="%.4f", step=0.001)
            metro_label = None
        else:
            station = find_station(chosen_station)
            lat, lon = station.lat, station.lon
            metro_label = chosen_station
            zone, coef, _ = get_rent_zone(lat, lon)
            st.caption(
                f"Координаты: {lat:.4f}, {lon:.4f}  ·  "
                f"Зона: {zone}  ·  Коэф. аренды: ×{coef}"
            )

        quest_type = st.selectbox(
            "Тип квеста",
            options=['Квест-Перформанс', 'Квест', 'Экшн-игра', 'Хоррор-кинотеатр'],
            help="Тип механики: с актёрами (перформанс) или без (классический квест)",
        )

        genre_options = KNOWN_GENRES
        genre = st.selectbox(
            "Жанр",
            options=genre_options,
            help="Жанровое позиционирование. Используется для оценки ниши.",
        )

        st.markdown("**Параметры продукта**")
        slot_price = st.number_input(
            "Цена слота, ₽",
            min_value=1000, max_value=20000, value=5500, step=500,
            help="Стоимость одной игры (одной команды), ₽",
        )
        team_size = st.number_input(
            "Макс. размер команды",
            min_value=2, max_value=15, value=6, step=1,
        )

    with col_right:
        st.markdown("**Финансовая модель**")
        capex = st.number_input(
            "CapEx (капитальные затраты), ₽",
            min_value=500_000, max_value=15_000_000,
            value=4_500_000, step=100_000,
            help="Ремонт, декорации, оборудование, реквизит",
        )

        st.markdown("**Операционные расходы (₽/месяц)**")
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            rent      = st.number_input("Аренда",     min_value=30_000,
                                         max_value=600_000, value=180_000, step=10_000)
            salary    = st.number_input("ФОТ",        min_value=50_000,
                                         max_value=500_000, value=120_000, step=10_000)
        with f_col2:
            marketing = st.number_input("Маркетинг",  min_value=10_000,
                                         max_value=300_000, value=50_000, step=5_000)
            other     = st.number_input("Прочие",     min_value=10_000,
                                         max_value=200_000, value=40_000, step=5_000)

        opex_monthly = rent + salary + marketing + other
        st.metric("Итого OpEx", f"{opex_monthly:,} ₽/мес")

        st.markdown("**График работы**")
        slots_per_day = st.number_input(
            "Слотов в день (макс.)",
            min_value=2, max_value=12, value=6, step=1,
            help="Сколько игр максимум в день вместит расписание",
        )
        work_days = st.number_input(
            "Рабочих дней в месяце",
            min_value=20, max_value=31, value=30, step=1,
        )

    submitted = st.form_submit_button(
        "Оценить проект",
        type="primary",
        use_container_width=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ОБРАБОТКА ОТПРАВКИ
# ─────────────────────────────────────────────────────────────────────────────
if submitted:
    new_input = ProjectInput(
        lat=lat, lon=lon, metro_station=metro_label,
        quest_type=quest_type, genre=genre,
        slot_price=slot_price, team_size=team_size,
        capex=capex, opex_monthly=opex_monthly,
        slots_per_day=slots_per_day,
        work_days_per_month=work_days,
    )
    # При новой отправке — сбрасываем оригинал
    st.session_state.evaluation_done = True
    st.session_state.current_input = new_input
    st.session_state.original_input = new_input


# ─────────────────────────────────────────────────────────────────────────────
# РЕНДЕРЫ
# ─────────────────────────────────────────────────────────────────────────────

VERDICT_LABELS = {
    'green':  'РЕКОМЕНДУЕТСЯ',
    'yellow': 'ТРЕБУЕТ ДОРАБОТКИ',
    'red':    'НЕ РЕКОМЕНДУЕТСЯ',
}

VERDICT_FILL_COLOR = {
    'green':  '#16a34a',
    'yellow': '#ca8a04',
    'red':    '#dc2626',
}

STRATEGY_BG = {
    'green':  '#dcfce7',
    'yellow': '#fef3c7',
    'red':    '#fee2e2',
}


def render_verdict(score):
    """Большой цветной блок с итоговым вердиктом."""
    label = VERDICT_LABELS[score.verdict]
    st.markdown(f"""
    <div class="verdict-block verdict-{score.verdict}">
        <div class="verdict-label">Итоговая оценка</div>
        <div style="display:flex;align-items:baseline;gap:24px;flex-wrap:wrap">
            <span class="verdict-score">{score.total:.2f} / 10</span>
            <span style="font-size:1.4rem;font-weight:600">{label}</span>
        </div>
        <div class="verdict-text">{score.verdict_text}</div>
    </div>
    """, unsafe_allow_html=True)


def render_blockers(score):
    if not score.has_blockers:
        return
    items = "".join(f"<li>{b}</li>" for b in score.blockers)
    st.markdown(f"""
    <div class="blocker-block">
        <strong>Блокирующие риски:</strong>
        <ul style="margin: 6px 0 0 0; padding-left: 22px">
            {items}
        </ul>
    </div>
    """, unsafe_allow_html=True)


def render_criteria(score):
    """4 карточки критериев: цветной бордер + балл + объяснение."""
    st.markdown("### Оценка по критериям")
    for c in score.criteria:
        st.markdown(f"""
        <div class="criterion-card {c.color}">
            <div style="display:flex;justify-content:space-between;align-items:baseline">
                <div class="criterion-name">{c.name}</div>
                <div class="criterion-score">{c.score:.1f} / 10
                    <span style="font-size:0.85rem;color:#6b7280;font-weight:400">
                        вес {c.weight:.0%}
                    </span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        # Объяснение — отдельным markdown, чтобы корректно работали ** и *
        st.markdown(c.explanation)


def render_radar(score):
    categories = [c.name for c in score.criteria]
    values = [c.score for c in score.criteria]
    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]

    fill_color = VERDICT_FILL_COLOR.get(score.verdict, '#94a3b8')

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed, theta=categories_closed,
        fill='toself',
        line=dict(color=fill_color, width=2),
        fillcolor=fill_color,
        opacity=0.30,
        name='Оценка',
        hovertemplate='%{theta}: %{r:.1f}/10<extra></extra>',
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10],
                            tickvals=[2, 4, 6, 8, 10],
                            gridcolor='#e5e7eb'),
            angularaxis=dict(gridcolor='#e5e7eb'),
        ),
        showlegend=False,
        height=380,
        margin=dict(t=20, b=20, l=80, r=80),
        paper_bgcolor='white',
    )
    st.plotly_chart(fig, use_container_width=True)


def render_input_summary(inp):
    """Компактная таблица параметров."""
    location_text = inp.metro_station or f"({inp.lat:.4f}, {inp.lon:.4f})"
    zone, coef, _ = get_rent_zone(inp.lat, inp.lon)
    st.markdown(f"""
| Параметр | Значение |
|---|---|
| Локация | **{location_text}** ({zone}, аренда ×{coef}) |
| Формат | **{inp.quest_type}**, жанр «{inp.genre}» |
| Цена слота | **{inp.slot_price:,.0f} ₽** |
| CapEx | **{inp.capex:,.0f} ₽** |
| OpEx | **{inp.opex_monthly:,.0f} ₽/мес** |
| Слотов/день · рабочих дней в мес | **{inp.slots_per_day} · {inp.work_days_per_month}** |
""")


def render_strategies(strategies):
    """Карточки стратегий с кнопкой «Применить»."""
    if not strategies:
        st.info(
            "Существенных одиночных улучшений не найдено. "
            "Если оценка низкая — попробуйте вручную скорректировать параметры в форме."
        )
        return

    st.markdown("### Стратегии улучшения")
    st.caption(
        "Каждая последующая стратегия добавляет правки к предыдущей. "
        "Нажмите «Применить», чтобы пересчитать проект с новыми параметрами."
    )

    cols = st.columns(len(strategies))
    for col, strat in zip(cols, strategies):
        bg = STRATEGY_BG.get(strat.new_score.verdict, '#f3f4f6')
        with col:
            st.markdown(f"""
            <div class="strategy-card" style="background: {bg}">
                <div class="strategy-label">{strat.label}</div>
                <div class="strategy-score">
                    {strat.new_score.total:.2f} / 10
                    <span style="font-size:0.9rem;color:#6b7280;font-weight:400">
                        (+{strat.delta:.2f})
                    </span>
                </div>
                <div class="strategy-summary">{strat.summary}</div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("**Изменения:**")
            for d in strat.change_descriptions:
                st.markdown(f"- {d}")

            if st.button(f"Применить стратегию",
                         key=f"apply_strat_{strat.label}",
                         use_container_width=True):
                st.session_state.current_input = strat.new_input
                st.rerun()


def render_singles(singles):
    if not singles:
        return
    for imp in singles[:8]:
        param_label = {
            'location': 'Локация',
            'price':    'Цена',
            'capex':    'CapEx',
            'opex':     'OpEx',
        }.get(imp.parameter, imp.parameter)

        title = f"{param_label}: +{imp.delta:.2f} → {imp.new_total_score:.2f}/10"
        with st.expander(title):
            st.markdown(imp.description)
            if st.button("Применить эту правку",
                         key=f"apply_single_{imp.parameter}_{imp.new_value}_{imp.new_total_score:.2f}"):
                st.session_state.current_input = imp.new_input
                st.rerun()


def render_compare_with_original(current_score):
    """Сравнение «до/после», если применили стратегию."""
    orig = st.session_state.original_input
    cur = st.session_state.current_input

    if orig is None or cur is None:
        return
    # Сравниваем по полям, а не по идентичности (после применения стратегии — другой объект)
    same = (orig.lat == cur.lat and orig.lon == cur.lon
            and orig.slot_price == cur.slot_price
            and orig.genre == cur.genre
            and orig.capex == cur.capex
            and orig.opex_monthly == cur.opex_monthly
            and orig.quest_type == cur.quest_type)
    if same:
        return

    original_score = evaluate_project(orig, df, survey)

    st.markdown("---")
    st.markdown("### Сравнение с исходным проектом")

    col_old, col_new = st.columns(2)
    with col_old:
        st.markdown("**Исходный проект**")
        st.markdown(f"""
        <div class="verdict-block verdict-{original_score.verdict}">
            <div class="verdict-label">Оценка</div>
            <div class="verdict-score">{original_score.total:.2f} / 10</div>
        </div>
        """, unsafe_allow_html=True)
        render_input_summary(orig)

    with col_new:
        st.markdown("**После корректировки**")
        delta_total = current_score.total - original_score.total
        delta_text = f"+{delta_total:.2f}" if delta_total >= 0 else f"{delta_total:.2f}"
        st.markdown(f"""
        <div class="verdict-block verdict-{current_score.verdict}">
            <div class="verdict-label">Оценка</div>
            <div class="verdict-score">{current_score.total:.2f} / 10
                <span style="font-size:1rem;font-weight:500;opacity:0.8">
                    ({delta_text})
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        render_input_summary(cur)

    if st.button("Сбросить и начать заново", type="secondary"):
        st.session_state.evaluation_done = False
        st.session_state.current_input = None
        st.session_state.original_input = None
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# РЕНДЕР ОТЧЁТА
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.evaluation_done:
    inp = st.session_state.current_input
    score = evaluate_project(inp, df, survey)

    st.markdown("---")
    st.markdown("## Результаты оценки")

    # Сводка введённых параметров — в expander, чтобы не загромождать
    with st.expander("Введённые параметры", expanded=False):
        render_input_summary(inp)

    # Большой цветной вердикт
    render_verdict(score)

    # Блокеры (если есть)
    render_blockers(score)

    # Критерии + радар (две колонки)
    col_crit, col_radar = st.columns([3, 2])
    with col_crit:
        render_criteria(score)
    with col_radar:
        st.markdown("### Профиль оценки")
        render_radar(score)

    # ── Блок «Сохранить для сравнения» ─────────────────────────────────────
    st.markdown("---")
    save_col1, save_col2 = st.columns([3, 2])
    with save_col1:
        default_name = inp.metro_station or f"({inp.lat:.3f}, {inp.lon:.3f})"
        default_name = f"{default_name} · {inp.genre} · {inp.slot_price:,.0f} ₽"
        save_name = st.text_input(
            "Название варианта (для сравнения с другими)",
            value=default_name,
            key="save_name_input",
        )
    with save_col2:
        st.markdown("&nbsp;", unsafe_allow_html=True)  # выравнивание по высоте с input
        already_saved = any(
            p['name'] == save_name for p in st.session_state.saved_projects
        )
        if st.button(
            "Сохранить для сравнения",
            type="secondary",
            use_container_width=True,
            disabled=already_saved,
            help=("Этот проект попадёт в раздел «Compare projects», "
                  "где можно сравнить несколько вариантов рядом."),
        ):
            st.session_state.saved_projects.append({
                'name':  save_name,
                'input': inp,
                'score': score,
            })
            st.success(f"Сохранено как «{save_name}». "
                       f"Всего вариантов в корзине: {len(st.session_state.saved_projects)}. "
                       f"Перейдите в раздел «Compare projects» для сравнения.")
        if already_saved:
            st.caption(f"Вариант с таким названием уже сохранён. "
                       f"Измените название, чтобы сохранить ещё раз.")
        elif st.session_state.saved_projects:
            st.caption(f"В корзине: {len(st.session_state.saved_projects)} "
                       f"вариант(ов).")

    # Если не зелёный — рекомендации
    if score.verdict != 'green':
        st.markdown("---")
        st.markdown("## Как улучшить оценку")

        with st.spinner("Подбираю стратегии…"):
            strategies = suggest_combined_strategy(inp, df, survey, score)
            singles = suggest_improvements(inp, df, survey, score, max_suggestions=8)

        render_strategies(strategies)

        if singles:
            with st.expander("Одиночные правки (только один параметр)"):
                render_singles(singles)

    # Сравнение «до/после», если применяли стратегию
    render_compare_with_original(score)

else:
    st.info("Заполните параметры выше и нажмите «Оценить проект».")
