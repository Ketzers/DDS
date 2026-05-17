"""
pages/02_Compare_projects.py — страница сравнения нескольких проектов.

Логика:
    1. Берёт проекты из st.session_state['saved_projects'] — те, что
       пользователь сохранил со страницы «Evaluate project».
    2. Показывает список карточек с параметрами и оценками.
    3. Если проектов ≥ 2 — рендерит сравнительные визуализации:
       - таблица параметров и скоров;
       - сводный радар с наложением контуров всех вариантов;
       - столбчатая диаграмма итоговых скоров;
       - текстовый разбор «победитель / сильные / слабые стороны».

Использует пакет sppr/.
"""

import os
import sys

import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ── Путь к корню ─────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sppr import evaluate_project, load_survey_metrics
from sppr.scoring import add_genre_column
from sppr.metro_stations import get_rent_zone


# ── Конфигурация ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Сравнить варианты — СППР",
    page_icon=None,
    layout="wide",
)

# CSS совпадает по стилю со страницей оценки
st.markdown("""
<style>
    .verdict-block {
        padding: 16px 20px;
        border-radius: 6px;
        border: 1px solid;
        margin: 8px 0;
    }
    .verdict-green   { background: #f0fdf4; border-color: #16a34a; color: #14532d; }
    .verdict-yellow  { background: #fefce8; border-color: #ca8a04; color: #713f12; }
    .verdict-red     { background: #fef2f2; border-color: #dc2626; color: #7f1d1d; }
    .verdict-score-small {
        font-size: 1.8rem; font-weight: 700; line-height: 1.1;
        font-variant-numeric: tabular-nums;
    }
    .project-card-header {
        font-size: 1rem; font-weight: 600; color: #111827;
        margin-bottom: 4px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА ДАННЫХ И СОСТОЯНИЕ
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

if 'saved_projects' not in st.session_state:
    st.session_state.saved_projects = []


# ─────────────────────────────────────────────────────────────────────────────
# ШАПКА
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("# Сравнение вариантов проектов")
st.markdown(
    "Здесь собраны проекты, которые вы сохранили на странице "
    "«Evaluate project». Сравните их по итоговым оценкам и "
    "профилям критериев — чтобы выбрать наиболее перспективный вариант."
)

st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# ПУСТАЯ КОРЗИНА
# ─────────────────────────────────────────────────────────────────────────────
saved = st.session_state.saved_projects
n = len(saved)

if n == 0:
    st.info(
        "**Корзина сравнения пуста.**  \n"
        "Перейдите на страницу «Evaluate project», оцените 2 или более проектов "
        "и нажмите «Сохранить для сравнения» — они появятся здесь."
    )
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# СПИСОК НАКОПЛЕННЫХ ПРОЕКТОВ
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"### В корзине: {n} вариант(ов)")

VERDICT_LABELS = {
    'green':  'РЕКОМЕНДУЕТСЯ',
    'yellow': 'ТРЕБУЕТ ДОРАБОТКИ',
    'red':    'НЕ РЕКОМЕНДУЕТСЯ',
}

cols = st.columns(min(n, 3))
for idx, project in enumerate(saved):
    inp = project['input']
    score = project['score']
    name = project['name']

    col = cols[idx % len(cols)]
    with col:
        st.markdown(f"""
        <div class="verdict-block verdict-{score.verdict}">
            <div class="project-card-header">{name}</div>
            <div class="verdict-score-small">
                {score.total:.2f} / 10
                <span style="font-size:0.85rem;font-weight:500;opacity:0.85">
                    · {VERDICT_LABELS[score.verdict]}
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        zone, coef, _ = get_rent_zone(inp.lat, inp.lon)
        st.markdown(f"""
- **Локация:** {inp.metro_station or '—'} ({zone})
- **Формат:** {inp.quest_type}, «{inp.genre}»
- **Цена:** {inp.slot_price:,.0f} ₽
- **CapEx / OpEx:** {inp.capex/1e6:.1f}М / {inp.opex_monthly/1e3:.0f}К
""")

        if st.button("Удалить", key=f"del_{idx}", type="secondary",
                     use_container_width=True):
            st.session_state.saved_projects.pop(idx)
            st.rerun()


# ── Кнопка очистки корзины целиком ─────────────────────────────────────
clear_col1, clear_col2 = st.columns([5, 1])
with clear_col2:
    if st.button("Очистить всё", type="secondary", use_container_width=True):
        st.session_state.saved_projects = []
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# СРАВНЕНИЕ (только если ≥ 2 проектов)
# ─────────────────────────────────────────────────────────────────────────────
if n < 2:
    st.markdown("---")
    st.info("Добавьте ещё один проект в корзину, чтобы увидеть сравнительные графики.")
    st.stop()


st.markdown("---")
st.markdown("## Сравнительный анализ")


# ── Сводная таблица ──────────────────────────────────────────────────────
st.markdown("### Сводная таблица")

table_rows = []
for project in saved:
    inp = project['input']
    score = project['score']
    zone, coef, _ = get_rent_zone(inp.lat, inp.lon)
    row = {
        'Вариант':       project['name'],
        'Итог':          f"{score.total:.2f}/10",
        'Вердикт':       VERDICT_LABELS[score.verdict],
        'Локация':       inp.metro_station or f"({inp.lat:.3f}, {inp.lon:.3f})",
        'Зона':          zone,
        'Тип':           inp.quest_type,
        'Жанр':          inp.genre,
        'Цена, ₽':       f"{inp.slot_price:,.0f}",
        'CapEx, ₽':      f"{inp.capex:,.0f}",
        'OpEx/мес, ₽':   f"{inp.opex_monthly:,.0f}",
    }
    # Добавляем баллы по каждому критерию
    for c in score.criteria:
        row[c.name] = f"{c.score:.1f}"
    table_rows.append(row)

st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


# ── Bar-chart итоговых скоров ──────────────────────────────────────────
chart_col, radar_col = st.columns([1, 1])

with chart_col:
    st.markdown("### Итоговые оценки")

    names  = [p['name'] for p in saved]
    totals = [p['score'].total for p in saved]
    colors = []
    color_map = {'green': '#16a34a', 'yellow': '#ca8a04', 'red': '#dc2626'}
    for p in saved:
        colors.append(color_map.get(p['score'].verdict, '#94a3b8'))

    # Сокращаем длинные имена для подписей оси
    short_names = [n[:25] + '…' if len(n) > 25 else n for n in names]

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        y=short_names, x=totals,
        marker_color=colors,
        text=[f"{t:.2f}" for t in totals],
        textposition='outside',
        orientation='h',
    ))
    fig_bar.add_vline(x=7.5, line_dash="dot", line_color="#16a34a",
                      annotation_text="зелёная зона",
                      annotation_position="top right",
                      annotation_font_size=10)
    fig_bar.add_vline(x=5.0, line_dash="dot", line_color="#ca8a04",
                      annotation_text="жёлтая зона",
                      annotation_position="bottom right",
                      annotation_font_size=10)
    fig_bar.update_layout(
        height=max(220, 60 * n + 80),
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis=dict(range=[0, 10.5], title="Балл"),
        yaxis=dict(title="", autorange='reversed'),
        showlegend=False,
        paper_bgcolor='white', plot_bgcolor='white',
    )
    st.plotly_chart(fig_bar, use_container_width=True)


# ── Сводный радар ──────────────────────────────────────────────────────
with radar_col:
    st.markdown("### Профили критериев")

    # Все варианты накладываем на одну сетку
    palette = ['#1e3a8a', '#dc2626', '#16a34a', '#ca8a04', '#7c3aed', '#0891b2']
    fig_radar = go.Figure()

    # Берём имена критериев из первого проекта
    categories = [c.name for c in saved[0]['score'].criteria]

    for idx, project in enumerate(saved):
        score = project['score']
        values = [c.score for c in score.criteria]
        cat_closed = categories + [categories[0]]
        val_closed = values + [values[0]]
        col = palette[idx % len(palette)]
        short_name = project['name'][:30] + '…' if len(project['name']) > 30 else project['name']

        fig_radar.add_trace(go.Scatterpolar(
            r=val_closed, theta=cat_closed,
            fill='toself',
            line=dict(color=col, width=2),
            fillcolor=col,
            opacity=0.20,
            name=short_name,
            hovertemplate='%{theta}: %{r:.1f}/10<extra>' + short_name + '</extra>',
        ))

    fig_radar.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10],
                            tickvals=[2, 4, 6, 8, 10], gridcolor='#e5e7eb'),
            angularaxis=dict(gridcolor='#e5e7eb'),
        ),
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=-0.25,
                    xanchor='center', x=0.5, font=dict(size=10)),
        height=max(380, 380 + (n - 2) * 25),
        margin=dict(t=20, b=20 + (n - 2) * 25, l=80, r=80),
        paper_bgcolor='white',
    )
    st.plotly_chart(fig_radar, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# ТЕКСТОВЫЙ РАЗБОР
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### Разбор вариантов")

# Победитель
ranked = sorted(saved, key=lambda p: -p['score'].total)
winner = ranked[0]
runner_up = ranked[1] if len(ranked) > 1 else None

verdict_color_class = f"verdict-{winner['score'].verdict}"

w_inp = winner['input']
w_score = winner['score']

if winner['score'].verdict == 'green':
    winner_intro = (f"**Лидер по итоговому баллу — «{winner['name']}» "
                    f"({winner['score'].total:.2f}/10, рекомендуется к запуску).**")
elif winner['score'].verdict == 'yellow':
    winner_intro = (f"**Лидер по итоговому баллу — «{winner['name']}» "
                    f"({winner['score'].total:.2f}/10), но требует доработки.**")
else:
    winner_intro = (f"**Лучший из имеющихся вариантов — «{winner['name']}» "
                    f"({winner['score'].total:.2f}/10), но даже он не рекомендуется. "
                    f"Возможно, стоит вернуться к доработке параметров.**")

st.markdown(winner_intro)

if runner_up is not None:
    delta = winner['score'].total - runner_up['score'].total
    if delta < 0.3:
        st.markdown(
            f"Близкий конкурент: «{runner_up['name']}» "
            f"({runner_up['score'].total:.2f}/10), отставание всего {delta:.2f} балла. "
            f"Выбор между ними определяется индивидуальными приоритетами по критериям."
        )

# Сильные и слабые стороны каждого варианта
st.markdown("**Сильные и слабые стороны каждого варианта:**")
for project in ranked:
    inp = project['input']
    score = project['score']
    sorted_crits = sorted(score.criteria, key=lambda c: -c.score)
    best_crit = sorted_crits[0]
    worst_crit = sorted_crits[-1]

    blocker_note = ""
    if score.has_blockers:
        blocker_note = f" **{len(score.blockers)} блокер(ов).**"

    st.markdown(
        f"- **{project['name']}** ({score.total:.2f}/10): "
        f"сильнее всего в «{best_crit.name.lower()}» ({best_crit.score:.1f}/10), "
        f"слабее всего в «{worst_crit.name.lower()}» ({worst_crit.score:.1f}/10).{blocker_note}"
    )
