"""
СППР: рынок квест-комнат Москвы
Запуск: streamlit run dashboard.py
Зависимости: pip install streamlit pandas folium streamlit-folium plotly scipy openpyxl scikit-learn

Страница «Изучить рынок» — конкурентная среда, аналитика, кластеры:
    Карта рынка     — KDE + маркеры + DBSCAN-кластеры (всё одним модулем)
    Аналитика рынка — 4 вложенных таба: Сводка / Структура и цены / Sentiment / Время
"""

import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
from scipy.stats import spearmanr
from sklearn.cluster import DBSCAN

warnings.filterwarnings('ignore')

# ── Конфигурация страницы ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Explore market — СППР",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS: тонкие донастройки поверх светлой темы из .streamlit/config.toml ──
st.markdown("""
<style>
    /* Боковая панель: добавляем тонкий правый бордер */
    section[data-testid="stSidebar"] {
        border-right: 1px solid #e5e7eb;
    }

    /* Кастомные «приборные» карточки метрик в верхней шапке */
    .metric-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        padding: 16px 20px;
        border-left: 3px solid #1e3a8a;
        margin-bottom: 8px;
    }
    .metric-value {
        font-size: 1.85rem;
        font-weight: 600;
        color: #111827;
        font-variant-numeric: tabular-nums;
    }
    .metric-label {
        font-size: 0.82rem;
        color: #6b7280;
        margin-top: 2px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    /* Заголовки секций */
    .section-header {
        font-size: 1.05rem;
        font-weight: 600;
        color: #1f2937;
        border-bottom: 1px solid #d1d5db;
        padding-bottom: 6px;
        margin-bottom: 16px;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# ЗАГРУЗКА ДАННЫХ
# ══════════════════════════════════════════════════════════════════════════════
_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # корень проекта (родитель pages/)

DATA_FILES = {
    'quests':  os.path.join(_DIR, 'mir_kvestov_full.xlsx'),
    'reviews': os.path.join(_DIR, 'reviews_sentiment.xlsx'),
}


def get_data_fingerprint():
    fp = {}
    for key, path in DATA_FILES.items():
        try:
            fp[key] = os.path.getmtime(path)
        except FileNotFoundError:
            fp[key] = None
    return fp


@st.cache_data
def load_data(fingerprint):
    df = pd.read_excel(DATA_FILES['quests'])
    df['Метро_чистое'] = df['Метро'].str.replace('м. ', '', regex=False).str.strip()

    try:
        reviews = pd.read_excel(DATA_FILES['reviews'])
    except FileNotFoundError:
        reviews = pd.DataFrame()

    return df, reviews


_fingerprint = get_data_fingerprint()
df, reviews = load_data(_fingerprint)

_quests_mtime = _fingerprint.get('quests')
_data_timestamp = (datetime.fromtimestamp(_quests_mtime).strftime('%d.%m.%Y %H:%M')
                   if _quests_mtime else 'неизвестно')


# ══════════════════════════════════════════════════════════════════════════════
# САЙДБАР: ФИЛЬТРЫ
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## Фильтры")
    st.markdown("---")

    all_types = sorted(df['Тип квеста'].unique().tolist())
    sel_types = st.multiselect("Тип квеста", options=all_types, default=all_types)

    price_min, price_max = int(df['цена_руб'].min()), int(df['цена_руб'].max())
    price_range = st.slider(
        "Цена слота, ₽",
        min_value=price_min, max_value=price_max,
        value=(price_min, price_max), step=500,
    )

    metros = sorted(df['Метро_чистое'].dropna().unique().tolist())
    sel_metros = st.multiselect(
        "Станция метро", options=metros, default=[], placeholder="Все станции",
    )

    occ_min = st.slider("Минимальная заполняемость, %", 0, 80, 0, 5)

    st.markdown("---")
    st.markdown("### Источник данных")
    st.markdown(f"""
    - Источник: Мир Квестов
    - Квестов: {len(df)} (топ по рейтингу)
    - Период наблюдения: окт 2025 – март 2026
    - Обновлено: {_data_timestamp}
    """)

    if st.button("Перезагрузить данные", use_container_width=True,
                 help="Принудительно перечитать Excel-файлы"):
        st.cache_data.clear()
        st.rerun()


# ── Применяем фильтры ──────────────────────────────────────────────────────
filt = df.copy()
filt = filt[filt['Тип квеста'].isin(sel_types)]
filt = filt[(filt['цена_руб'] >= price_range[0]) & (filt['цена_руб'] <= price_range[1])]
if sel_metros:
    filt = filt[filt['Метро_чистое'].isin(sel_metros)]
filt = filt[filt['заполняемость'] >= occ_min / 100]


# ══════════════════════════════════════════════════════════════════════════════
# ВЕРХНЯЯ ШАПКА
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("# Изучить рынок")
st.markdown("Конкурентная среда московского рынка квест-комнат. "
            "Используйте фильтры в боковой панели, чтобы сузить выборку, "
            "и переключайтесь между картой и аналитикой.")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f"""<div class="metric-card">
        <div class="metric-value">{len(filt)}</div>
        <div class="metric-label">квест-комнат в выборке</div>
    </div>""", unsafe_allow_html=True)
with col2:
    med_price = int(filt['цена_руб'].median()) if len(filt) > 0 else 0
    st.markdown(f"""<div class="metric-card">
        <div class="metric-value">{med_price:,} ₽</div>
        <div class="metric-label">медианная цена слота</div>
    </div>""", unsafe_allow_html=True)
with col3:
    avg_occ = filt['заполняемость'].mean() if len(filt) > 0 else 0
    st.markdown(f"""<div class="metric-card">
        <div class="metric-value">{avg_occ:.0%}</div>
        <div class="metric-label">средняя заполняемость</div>
    </div>""", unsafe_allow_html=True)
with col4:
    top_type = filt['Тип квеста'].value_counts().index[0] if len(filt) > 0 else "—"
    top_type_short = top_type.replace('Квест-', '').replace('Экшн-игра', 'Экшн')
    st.markdown(f"""<div class="metric-card">
        <div class="metric-value">{top_type_short}</div>
        <div class="metric-label">доминирующий формат</div>
    </div>""", unsafe_allow_html=True)

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНЫЕ ТАБЫ (3 ШТ.)
# ══════════════════════════════════════════════════════════════════════════════
tab_map, tab_analytics = st.tabs([
    "Карта рынка",
    "Аналитика рынка",
])


# ══════════════════════════════════════════════════════════════════════════════
# ТАБ 1: КАРТА РЫНКА (объединяет старые «Карта» + «DBSCAN»)
# ══════════════════════════════════════════════════════════════════════════════
with tab_map:
    st.markdown('<div class="section-header">Геопространственный анализ конкурентной среды</div>',
                unsafe_allow_html=True)

    map_col, ctrl_col = st.columns([3, 1])

    with ctrl_col:
        st.markdown("**Слои карты**")
        show_heatmap  = st.checkbox("Тепловая карта (KDE)", value=True)
        show_markers  = st.checkbox("Маркеры квестов",      value=True)
        show_clusters = st.checkbox("Кластеры (DBSCAN)",    value=False,
                                    help="Включает режим пространственной кластеризации")

        if not show_clusters:
            st.markdown("**Цвет маркеров**")
            color_by = st.radio(
                "color_by",
                ["Заполняемость", "Цена", "Тип квеста", "Тональность"],
                label_visibility="collapsed",
            )
        else:
            color_by = None

        if show_clusters:
            st.markdown("---")
            st.markdown("**Параметры кластеризации**")
            eps_km = st.slider(
                "Радиус ε, км",
                min_value=0.3, max_value=2.0, value=0.9, step=0.1,
                help="Макс. расстояние между точками в одном кластере (≈ пешеходная доступность)",
            )
            min_pts = st.slider(
                "MinPts", min_value=2, max_value=6, value=3, step=1,
                help="Мин. число квестов для формирования кластера",
            )
            st.caption(f"ε = {eps_km} км · ≈ {eps_km*10:.0f} мин пешком")

        st.markdown("---")
        st.markdown(f"**Показано:** {len(filt)} квестов")
        if len(filt) > 0:
            top_metros = filt['Метро_чистое'].value_counts().head(3)
            st.markdown("**Топ-3 по концентрации:**")
            for metro, cnt in top_metros.items():
                st.markdown(f"— {metro}: {cnt}")

    with map_col:
        if len(filt) == 0:
            st.warning("Нет данных по заданным фильтрам.")
        else:
            center_lat = filt['lat'].mean()
            center_lon = filt['lon'].mean()
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=11,
                tiles="CartoDB positron",
            )

            if show_heatmap:
                heat_data = filt[['lat', 'lon']].values.tolist()
                HeatMap(
                    heat_data,
                    radius=30, blur=25, max_zoom=13,
                    gradient={0.2: '#3b82f6', 0.5: '#f59e0b', 0.8: '#ef4444'},
                ).add_to(m)

            # ── РЕЖИМ A: маркеры с раскраской ───────────────────────────────
            if show_markers and not show_clusters:
                def get_color(row):
                    if color_by == "Заполняемость":
                        occ = row['заполняемость']
                        if occ >= 0.60: return '#16a34a'
                        elif occ >= 0.45: return '#f59e0b'
                        else: return '#dc2626'
                    elif color_by == "Цена":
                        p = row['цена_руб']
                        if p >= 7000: return '#7c3aed'
                        elif p >= 5000: return '#2563eb'
                        else: return '#0891b2'
                    elif color_by == "Тональность":
                        s = row.get('avg_sentiment')
                        if pd.isna(s): return '#9ca3af'
                        if s >= 0.65: return '#16a34a'
                        elif s >= 0.55: return '#84cc16'
                        elif s >= 0.45: return '#f59e0b'
                        else: return '#dc2626'
                    else:
                        type_colors = {
                            'Квест-Перформанс': '#dc2626',
                            'Квест':            '#2563eb',
                            'Экшн-игра':        '#16a34a',
                            'Хоррор-кинотеатр': '#7c3aed',
                        }
                        return type_colors.get(row['Тип квеста'], '#6b7280')

                for _, row in filt.iterrows():
                    color = get_color(row)
                    sentiment_line = ""
                    if 'avg_sentiment' in row and pd.notna(row.get('avg_sentiment')):
                        s = row['avg_sentiment']
                        s_color = '#16a34a' if s > 0.5 else '#f59e0b' if s > 0.3 else '#dc2626'
                        s_label = ('сильно позитивные' if s > 0.5
                                   else 'позитивные' if s > 0.3
                                   else 'смешанные')
                        sentiment_line = (f"Тональность: "
                                          f"<b style='color:{s_color}'>{s:+.2f}</b> "
                                          f"<span style='color:#6b7280;font-size:11px'>"
                                          f"({s_label})</span><br>")

                    popup_html = f"""
                    <div style="min-width:200px;font-family:sans-serif">
                        <b style="font-size:14px">{row['Название']}</b><br>
                        <span style="color:#6b7280">{row['Тип квеста']}</span><br><br>
                        Цена: <b>{row['цена_руб']:,} ₽</b> / слот<br>
                        Рейтинг: <b>{row['Народный рейтинг']}</b> ({row['кол_оценок']} оценок)<br>
                        Заполняемость: <b>{row['заполняемость']:.0%}</b><br>
                        {sentiment_line}Метро: {row['Метро']}<br>
                        Адрес: {str(row['Адрес'])[:60]}
                    </div>
                    """
                    folium.CircleMarker(
                        location=[row['lat'], row['lon']],
                        radius=7,
                        color=color, fill=True, fill_color=color, fill_opacity=0.75,
                        popup=folium.Popup(popup_html, max_width=250),
                        tooltip=f"{row['Название']} — {row['цена_руб']:,}₽",
                    ).add_to(m)

                if color_by == "Заполняемость":
                    legend_html = """
                    <div style="position:fixed;bottom:30px;left:30px;background:white;
                         padding:10px 12px;border:1px solid #e5e7eb;border-radius:4px;
                         box-shadow:0 2px 6px rgba(0,0,0,.08);
                         font-size:12px;font-family:sans-serif;z-index:1000;color:#111827">
                        <b>Заполняемость</b><br>
                        <span style="color:#16a34a">●</span> ≥ 60% (высокая)<br>
                        <span style="color:#f59e0b">●</span> 45–60% (средняя)<br>
                        <span style="color:#dc2626">●</span> &lt; 45% (низкая)
                    </div>"""
                    m.get_root().html.add_child(folium.Element(legend_html))

            # ── РЕЖИМ B: DBSCAN-кластеризация ────────────────────────────────
            if show_clusters and len(filt) >= min_pts:
                coords = filt[['lat', 'lon']].values
                eps_deg = eps_km / 111
                db = DBSCAN(eps=eps_deg, min_samples=min_pts).fit(coords)
                filt_clustered = filt.copy()
                filt_clustered['cluster'] = db.labels_

                cluster_colors = [
                    '#dc2626', '#2563eb', '#16a34a', '#f59e0b',
                    '#7c3aed', '#0891b2', '#db2777', '#65a30d',
                    '#ea580c', '#0ea5e9', '#a855f7', '#10b981',
                ]

                for cid in sorted(set(db.labels_)):
                    if cid == -1:
                        continue
                    sub = filt_clustered[filt_clustered['cluster'] == cid]
                    color = cluster_colors[cid % len(cluster_colors)]

                    c_lat = sub['lat'].mean()
                    c_lon = sub['lon'].mean()
                    folium.Circle(
                        location=[c_lat, c_lon],
                        radius=eps_km * 1000,
                        color=color, fill=True, fill_opacity=0.12, weight=2,
                        popup=f"Кластер {cid+1}: {len(sub)} квестов",
                    ).add_to(m)

                    if show_markers:
                        for _, row in sub.iterrows():
                            folium.CircleMarker(
                                location=[row['lat'], row['lon']],
                                radius=6,
                                color=color, fill=True, fill_color=color, fill_opacity=0.85,
                                tooltip=f"Кластер {cid+1}: {row['Название']}",
                                popup=folium.Popup(
                                    f"<b>{row['Название']}</b><br>"
                                    f"Кластер {cid+1}<br>"
                                    f"Цена: {row['цена_руб']:,} ₽<br>"
                                    f"Заполняемость: {row['заполняемость']:.0%}<br>"
                                    f"Метро: {row['Метро']}",
                                    max_width=220,
                                ),
                            ).add_to(m)

                if show_markers:
                    noise = filt_clustered[filt_clustered['cluster'] == -1]
                    for _, row in noise.iterrows():
                        folium.CircleMarker(
                            location=[row['lat'], row['lon']],
                            radius=5,
                            color='#9ca3af', fill=True, fill_color='#9ca3af', fill_opacity=0.6,
                            tooltip=f"Одиночка: {row['Название']}",
                            popup=folium.Popup(
                                f"<b>{row['Название']}</b><br>"
                                f"<span style='color:#16a34a'>Вне кластеров</span><br>"
                                f"Цена: {row['цена_руб']:,} ₽<br>"
                                f"Заполняемость: {row['заполняемость']:.0%}<br>"
                                f"Метро: {row['Метро']}",
                                max_width=220,
                            ),
                        ).add_to(m)

            st_folium(m, width=None, height=520, returned_objects=[])

            if show_clusters and len(filt) >= min_pts:
                st.markdown("---")
                st.markdown("**Результаты кластеризации**")

                n_clusters = len(set(db.labels_)) - (1 if -1 in db.labels_ else 0)
                n_noise = (db.labels_ == -1).sum()

                mc1, mc2, mc3, mc4 = st.columns(4)
                with mc1:
                    st.metric("Найдено кластеров", n_clusters)
                with mc2:
                    st.metric("В кластерах", len(filt_clustered) - n_noise)
                with mc3:
                    st.metric("Одиночных точек", n_noise,
                              help="Квесты без конкурентов в радиусе — потенциально выгодные локации")
                with mc4:
                    largest = 0
                    if n_clusters > 0:
                        largest = max((db.labels_ == c).sum() for c in set(db.labels_) if c != -1)
                    st.metric("Крупнейший кластер", f"{largest}")

                noise_df = filt_clustered[filt_clustered['cluster'] == -1]
                if len(noise_df) > 0:
                    st.markdown("**Локации без прямых конкурентов в радиусе ε:**")
                    one_table = noise_df[['Название', 'Тип квеста', 'Метро_чистое',
                                          'цена_руб', 'заполняемость']].copy()
                    one_table['цена_руб'] = one_table['цена_руб'].apply(lambda x: f"{x:,} ₽")
                    one_table['заполняемость'] = one_table['заполняемость'].apply(lambda x: f"{x:.0%}")
                    one_table.columns = ['Квест', 'Тип', 'Метро', 'Цена', 'Заполняемость']
                    st.dataframe(one_table.head(15), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ТАБ 2: АНАЛИТИКА РЫНКА → 4 вложенных подтаба
# ══════════════════════════════════════════════════════════════════════════════
with tab_analytics:
    st.markdown('<div class="section-header">Аналитика рынка квест-комнат</div>',
                unsafe_allow_html=True)

    if len(filt) < 5:
        st.warning("Недостаточно данных для анализа. Снимите часть фильтров.")
    else:
        sub_summary, sub_structure, sub_sentiment = st.tabs([
            "Сводка",
            "Структура и цены",
            "Восприятие клиентами",
        ])

        filt_names = filt['Название'].tolist()

        # ──────────────────────────────────────────────────────────────────────
        # ПОДТАБ 2.1: СВОДКА ПО РЫНКУ
        # ──────────────────────────────────────────────────────────────────────
        with sub_summary:
            st.markdown("Главные выводы по текущей выборке. "
                        "Меняются автоматически при изменении фильтров.")

            if len(filt) >= 3:
                coords_i = filt[['lat', 'lon']].values
                db_i = DBSCAN(eps=0.9/111, min_samples=3).fit(coords_i)
                n_clust_i = len(set(db_i.labels_)) - (1 if -1 in db_i.labels_ else 0)
                n_noise_i = (db_i.labels_ == -1).sum()
            else:
                n_clust_i, n_noise_i = 0, 0

            # ── Три ключевых блока в строку ─────────────────────────────────
            col_geo, col_genre, col_price = st.columns(3)

            # География
            with col_geo:
                top_metros = filt['Метро_чистое'].value_counts().head(3)
                top3_share = top_metros.sum() / len(filt) * 100
                top_text = "\n".join([
                    f"— **{metro}** — {cnt} ({cnt/len(filt)*100:.0f}%)"
                    for metro, cnt in top_metros.items()
                ])
                st.info(f"""**География**

Топ-3 зон концентрации:

{top_text}

{top3_share:.0f}% рынка в 3 зонах. Найдено **{n_clust_i}** кластеров,
**{n_noise_i}** «одиночек» вне кластеров.""")

            # Жанры
            with col_genre:
                types_dist = filt['Тип квеста'].value_counts(normalize=True) * 100
                dominant = types_dist.index[0]
                dominant_pct = types_dist.iloc[0]
                others_lines = "\n".join([
                    f"— {t}: {pct:.0f}%" for t, pct in types_dist.iloc[1:4].items()
                ])
                st.warning(f"""**Структура рынка**

Доминирует **{dominant}** ({dominant_pct:.0f}%).

Прочие типы:

{others_lines}

Высокая внутрижанровая конкуренция в доминирующем сегменте.""")

            # Цены
            with col_price:
                med_price_s = filt['цена_руб'].median()
                q1 = filt['цена_руб'].quantile(0.25)
                q3 = filt['цена_руб'].quantile(0.75)
                n_in_iqr = ((filt['цена_руб'] >= q1) & (filt['цена_руб'] <= q3)).sum()

                premium = filt[filt['цена_руб'] > q3]
                cheap = filt[filt['цена_руб'] < q1]
                premium_occ = premium['заполняемость'].mean() if len(premium) > 0 else 0
                cheap_occ = cheap['заполняемость'].mean() if len(cheap) > 0 else 0

                premium_word = "эффективнее" if premium_occ > cheap_occ else "не эффективнее"

                st.info(f"""**Цены и заполняемость**

Медиана: **{med_price_s:,.0f} ₽**, Q1–Q3: **{q1:,.0f}–{q3:,.0f} ₽**.

В коридоре Q1–Q3 — **{n_in_iqr} из {len(filt)}** квестов.

Премиум ({premium_occ:.0%} заполн.) {premium_word} эконома ({cheap_occ:.0%}).
Цена не основной драйвер спроса.""")

            st.markdown("---")

            # ── Подробные показатели в expander ─────────────────────────────
            with st.expander("Подробные показатели (корреляции, sentiment, ориентиры)"):

                st.markdown("**Статистические связи (ρ Спирмена)**")
                corr_pairs = [
                    ('цена_руб', 'заполняемость', 'Цена ↔ Заполняемость'),
                    ('цена_руб', 'кол_оценок', 'Цена ↔ Популярность'),
                    ('заполняемость', 'кол_оценок', 'Заполняемость ↔ Популярность'),
                    ('макс_игроков', 'цена_руб', 'Размер команды ↔ Цена'),
                ]
                corr_rows = []
                for c1, c2, name in corr_pairs:
                    if c1 in filt.columns and c2 in filt.columns and len(filt) >= 5:
                        try:
                            rho, pval = spearmanr(filt[c1], filt[c2])
                            sig = "значимая" if pval < 0.05 else "незначимая"
                            strength = ("сильная" if abs(rho) > 0.7
                                       else "умеренная" if abs(rho) > 0.4
                                       else "слабая" if abs(rho) > 0.2
                                       else "очень слабая/отсутствует")
                            corr_rows.append({
                                'Пара переменных': name,
                                'ρ (rho)': f"{rho:+.3f}",
                                'p-value': f"{pval:.3f}",
                                'Значимость': sig,
                                'Сила связи': strength,
                            })
                        except Exception:
                            pass
                if corr_rows:
                    st.dataframe(pd.DataFrame(corr_rows), use_container_width=True,
                                 hide_index=True)

                # Sentiment-сводка
                if 'avg_sentiment' in filt.columns and filt['avg_sentiment'].notna().any():
                    st.markdown("**Восприятие клиентами**")
                    sent_data = filt.dropna(subset=['avg_sentiment'])
                    avg_sent = sent_data['avg_sentiment'].mean()
                    top3 = sent_data.nlargest(3, 'avg_sentiment')[['Название', 'avg_sentiment']]
                    bot3 = sent_data.nsmallest(3, 'avg_sentiment')[['Название', 'avg_sentiment']]
                    top_text = ", ".join([f"{r['Название']} ({r['avg_sentiment']:+.2f})"
                                          for _, r in top3.iterrows()])
                    bot_text = ", ".join([f"{r['Название']} ({r['avg_sentiment']:+.2f})"
                                          for _, r in bot3.iterrows()])
                    st.markdown(f"Средний sentiment по выборке: **{avg_sent:+.3f}** из [−1; +1].  \n"
                                f"**Лидеры:** {top_text}.  \n"
                                f"**Проблемные:** {bot_text}.")

                # Ориентиры
                st.markdown("**Реалистичные ориентиры для бизнес-плана** (медианы по выборке)")
                realistic_occ = filt['заполняемость'].mean()
                realistic_price = filt['цена_руб'].median()
                realistic_revenue = realistic_price * 6 * realistic_occ * 30
                st.markdown(f"""
| Параметр | Значение |
|---|---|
| Цена слота | **{realistic_price:,.0f} ₽** |
| Ожидаемая заполняемость | **{realistic_occ:.0%}** |
| Выручка/мес (6 слотов × 30 дней) | **~{realistic_revenue:,.0f} ₽** |
| Пиковые дни | **Пт–Вс** |
| Пиковый сезон | **Октябрь** (Хэллоуин) |
| Спад | **Январь** |
""")

        # ──────────────────────────────────────────────────────────────────────
        # ПОДТАБ 2.2: СТРУКТУРА И ЦЕНЫ
        # ──────────────────────────────────────────────────────────────────────
        with sub_structure:
            row1_col1, row1_col2 = st.columns(2)

            with row1_col1:
                st.markdown("**Структура рынка по типам**")
                type_counts = filt['Тип квеста'].value_counts().reset_index()
                type_counts.columns = ['Тип', 'Количество']
                fig_pie = px.pie(
                    type_counts, values='Количество', names='Тип',
                    color_discrete_sequence=['#1e3a8a','#3b82f6','#60a5fa','#93c5fd'],
                    hole=0.45,
                )
                fig_pie.update_traces(textposition='outside', textinfo='percent+label')
                fig_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10),
                                      showlegend=False, height=300,
                                      paper_bgcolor='white', plot_bgcolor='white')
                st.plotly_chart(fig_pie, use_container_width=True)

            with row1_col2:
                st.markdown("**Ценовой бенчмаркинг**")
                user_price = st.number_input(
                    "Ваша цена слота, ₽ — для сравнения",
                    min_value=500, max_value=20000, value=5500, step=500,
                )
                fig_box = go.Figure()
                for ttype in filt['Тип квеста'].unique():
                    sub = filt[filt['Тип квеста'] == ttype]['цена_руб']
                    fig_box.add_trace(go.Box(
                        y=sub, name=ttype.replace('Квест-', ''),
                        boxmean=True, marker_color='#1e3a8a',
                    ))
                fig_box.add_hline(
                    y=user_price, line_dash="dash", line_color="#dc2626",
                    annotation_text=f"Ваша цена: {user_price:,} ₽",
                    annotation_position="top right",
                )
                fig_box.update_layout(margin=dict(t=10, b=10, l=10, r=10),
                                      height=300, yaxis_title="Цена слота, ₽",
                                      showlegend=False,
                                      paper_bgcolor='white', plot_bgcolor='white')
                st.plotly_chart(fig_box, use_container_width=True)

                median_price = filt['цена_руб'].median()
                if user_price < median_price * 0.85:
                    price_msg = (f"Ниже медианы на "
                                 f"{(median_price - user_price):,.0f} ₽ — конкурентная цена")
                elif user_price > median_price * 1.15:
                    price_msg = (f"Выше медианы на "
                                 f"{(user_price - median_price):,.0f} ₽ — премиум")
                else:
                    price_msg = f"В пределах медианы (медиана: {median_price:,.0f} ₽)"
                st.info(price_msg)

            st.markdown("---")
            row2_col1, row2_col2 = st.columns(2)

            with row2_col1:
                st.markdown("**Зависимость заполняемости от цены**")
                corr_val, p_val = spearmanr(filt['цена_руб'], filt['заполняемость'])
                fig_scatter = px.scatter(
                    filt, x='цена_руб', y='заполняемость',
                    color='Тип квеста', size='кол_оценок', hover_name='Название',
                    hover_data={'цена_руб': True, 'заполняемость': ':.1%',
                                'кол_оценок': True, 'Метро_чистое': True},
                    color_discrete_sequence=['#1e3a8a','#3b82f6','#16a34a','#dc2626'],
                    labels={'цена_руб': 'Цена слота, ₽', 'заполняемость': 'Заполняемость',
                            'кол_оценок': 'Кол-во оценок'},
                )
                if len(filt) >= 3:
                    x_vals = filt['цена_руб'].values
                    y_vals = filt['заполняемость'].values
                    z = np.polyfit(x_vals, y_vals, 1)
                    p = np.poly1d(z)
                    x_line = np.linspace(x_vals.min(), x_vals.max(), 100)
                    fig_scatter.add_trace(go.Scatter(
                        x=x_line, y=p(x_line),
                        mode='lines', line=dict(color='#6b7280', width=1.5, dash='dot'),
                        name='Тренд', showlegend=False,
                    ))
                fig_scatter.update_layout(margin=dict(t=10, b=10, l=10, r=10),
                                          height=320, yaxis_tickformat='.0%',
                                          paper_bgcolor='white', plot_bgcolor='white')
                st.plotly_chart(fig_scatter, use_container_width=True)
                sig = "значимая" if p_val < 0.05 else "незначимая"
                direction = "положительная" if corr_val > 0 else "отрицательная"
                st.caption(
                    f"Корреляция Спирмена: ρ = {corr_val:.3f} ({direction}, {sig}, p = {p_val:.3f})"
                )

            with row2_col2:
                st.markdown("**Топ-10 по заполняемости**")
                top10 = filt.nlargest(10, 'заполняемость')[
                    ['Название', 'Тип квеста', 'цена_руб', 'заполняемость']
                ].copy()
                top10['заполняемость'] = top10['заполняемость'].apply(lambda x: f'{x:.0%}')
                top10['цена_руб'] = top10['цена_руб'].apply(lambda x: f'{x:,} ₽')
                top10.columns = ['Название', 'Тип', 'Цена', 'Заполняемость']
                st.dataframe(top10, use_container_width=True, hide_index=True, height=320)

            st.markdown("---")
            st.markdown("**Аутсайдеры по заполняемости**")
            bot10 = filt.nsmallest(10, 'заполняемость')[
                ['Название', 'Тип квеста', 'цена_руб', 'заполняемость']
            ].copy()
            bot10['заполняемость'] = bot10['заполняемость'].apply(lambda x: f'{x:.0%}')
            bot10['цена_руб'] = bot10['цена_руб'].apply(lambda x: f'{x:,} ₽')
            bot10.columns = ['Название', 'Тип', 'Цена', 'Заполняемость']
            st.dataframe(bot10, use_container_width=True, hide_index=True)

        # ──────────────────────────────────────────────────────────────────────
        # ПОДТАБ 2.3: ВОСПРИЯТИЕ КЛИЕНТАМИ (sentiment)
        # ──────────────────────────────────────────────────────────────────────
        with sub_sentiment:
            st.markdown("""Автоматический анализ тональности отзывов методом словарного подхода
            с лемматизацией (pymorphy3). Каждый отзыв классифицирован по шкале от −1.0
            (сильно негативный) до +1.0 (сильно позитивный).""")

            if len(reviews) == 0:
                st.warning("Файл с отзывами не найден. Положите `reviews_sentiment.xlsx` в папку.")
            else:
                rev_filt = reviews[reviews['quest_name'].isin(filt_names)].copy()

                if len(rev_filt) == 0:
                    st.warning("В текущей выборке нет отзывов. Расширьте фильтры.")
                else:
                    m1, m2, m3, m4 = st.columns(4)
                    with m1:
                        st.metric("Всего отзывов", f"{len(rev_filt):,}")
                    with m2:
                        avg_sent_v = rev_filt['score_norm'].mean()
                        st.metric("Средний sentiment", f"{avg_sent_v:+.3f}",
                                  delta="позитивный" if avg_sent_v > 0.1 else "нейтральный")
                    with m3:
                        pos_share_all = (rev_filt['category']
                                         .isin(['positive', 'strongly_positive'])).mean()
                        st.metric("Доля позитивных", f"{pos_share_all:.0%}")
                    with m4:
                        neg_count = rev_filt['category'].isin(['negative', 'strongly_negative']).sum()
                        st.metric("Негативных", f"{neg_count}",
                                  delta=f"{neg_count/len(rev_filt):.1%} от общего")

                    st.markdown("---")

                    row1_col1, row1_col2 = st.columns(2)
                    cat_order = ['strongly_negative', 'negative', 'neutral',
                                 'positive', 'strongly_positive']
                    cat_labels = {
                        'strongly_negative': 'Сильно негативные',
                        'negative':          'Негативные',
                        'neutral':           'Нейтральные',
                        'positive':          'Позитивные',
                        'strongly_positive': 'Сильно позитивные',
                    }
                    cat_colors = {
                        'strongly_negative': '#dc2626',
                        'negative':          '#f59e0b',
                        'neutral':           '#9ca3af',
                        'positive':          '#84cc16',
                        'strongly_positive': '#16a34a',
                    }

                    with row1_col1:
                        st.markdown("**Распределение по тональности**")
                        cat_counts = rev_filt['category'].value_counts().reindex(cat_order).fillna(0)

                        fig_cat = go.Figure()
                        for cat in cat_order:
                            cnt = int(cat_counts[cat])
                            fig_cat.add_trace(go.Bar(
                                x=[cat_labels[cat]], y=[cnt],
                                marker_color=cat_colors[cat],
                                text=f"{cnt} ({cnt/len(rev_filt):.1%})",
                                textposition='outside', showlegend=False,
                            ))
                        fig_cat.update_layout(margin=dict(t=10, b=10, l=10, r=10),
                                              height=320, yaxis_title="Количество отзывов",
                                              paper_bgcolor='white', plot_bgcolor='white')
                        st.plotly_chart(fig_cat, use_container_width=True)

                    with row1_col2:
                        st.markdown("**Валидация: тональность vs звёздный рейтинг**")
                        val_data = rev_filt.dropna(subset=['rating', 'score_norm'])
                        if len(val_data) > 5:
                            val_agg = val_data.groupby('rating').agg(
                                sentiment=('score_norm', 'mean'),
                                count=('score_norm', 'count'),
                            ).reset_index()

                            fig_val = go.Figure()
                            fig_val.add_trace(go.Bar(
                                x=val_agg['rating'].astype(str) + '★',
                                y=val_agg['sentiment'],
                                marker_color=[cat_colors['strongly_negative'] if s < -0.1
                                              else cat_colors['neutral'] if s < 0.3
                                              else cat_colors['positive'] if s < 0.5
                                              else cat_colors['strongly_positive']
                                              for s in val_agg['sentiment']],
                                text=[f"{s:+.2f}<br>(n={int(c)})"
                                      for s, c in zip(val_agg['sentiment'], val_agg['count'])],
                                textposition='outside', showlegend=False,
                            ))
                            fig_val.add_hline(y=0, line_dash="dash", line_color="#9ca3af")
                            fig_val.update_layout(margin=dict(t=30, b=10, l=10, r=10),
                                                  height=320, yaxis_title="Средний sentiment",
                                                  yaxis_range=[-0.6, 1.0],
                                                  paper_bgcolor='white', plot_bgcolor='white')
                            st.plotly_chart(fig_val, use_container_width=True)

                            rho_v, pval_v = spearmanr(val_data['rating'], val_data['score_norm'])
                            st.caption(f"ρ = {rho_v:+.3f}, p = {pval_v:.4f} — "
                                       f"{'значимая монотонная связь' if pval_v < 0.05 else 'незначимая'}")

                    st.markdown("---")

                    st.markdown("**Рейтинг квестов по тональности**")
                    quest_agg = rev_filt.groupby('quest_name').agg(
                        reviews=('score_norm', 'count'),
                        sentiment=('score_norm', 'mean'),
                        avg_rating=('rating', 'mean'),
                    ).round(3).reset_index()
                    quest_agg = quest_agg[quest_agg['reviews'] >= 3]

                    tq1, tq2 = st.columns(2)
                    with tq1:
                        st.markdown("Топ-10")
                        top_sent = quest_agg.nlargest(10, 'sentiment')[
                            ['quest_name', 'reviews', 'sentiment', 'avg_rating']
                        ].copy()
                        top_sent.columns = ['Квест', 'Отзывов', 'Sentiment', 'Ср. рейтинг']
                        top_sent['Sentiment'] = top_sent['Sentiment'].apply(lambda x: f"{x:+.3f}")
                        top_sent['Ср. рейтинг'] = top_sent['Ср. рейтинг'].apply(
                            lambda x: f"{x:.2f}★" if pd.notna(x) else '—')
                        st.dataframe(top_sent, use_container_width=True, hide_index=True)

                    with tq2:
                        st.markdown("Нижние 10 (проблемные)")
                        bot_sent = quest_agg.nsmallest(10, 'sentiment')[
                            ['quest_name', 'reviews', 'sentiment', 'avg_rating']
                        ].copy()
                        bot_sent.columns = ['Квест', 'Отзывов', 'Sentiment', 'Ср. рейтинг']
                        bot_sent['Sentiment'] = bot_sent['Sentiment'].apply(lambda x: f"{x:+.3f}")
                        bot_sent['Ср. рейтинг'] = bot_sent['Ср. рейтинг'].apply(
                            lambda x: f"{x:.2f}★" if pd.notna(x) else '—')
                        st.dataframe(bot_sent, use_container_width=True, hide_index=True)

                    st.markdown("---")

                    st.markdown("**Связь тональности с бизнес-метриками**")
                    q_metrics = quest_agg.merge(
                        filt[['Название', 'заполняемость', 'кол_оценок', 'цена_руб']],
                        left_on='quest_name', right_on='Название',
                        how='inner',
                    )

                    cq1, cq2 = st.columns(2)
                    with cq1:
                        st.markdown("*Тональность ↔ Заполняемость*")
                        if len(q_metrics) >= 5:
                            rho_occ, p_occ = spearmanr(q_metrics['sentiment'], q_metrics['заполняемость'])
                            fig_so = px.scatter(
                                q_metrics, x='sentiment', y='заполняемость',
                                hover_name='quest_name', color='avg_rating',
                                color_continuous_scale=['#dc2626', '#f59e0b', '#16a34a'],
                                labels={'sentiment': 'Sentiment',
                                        'заполняемость': 'Заполняемость',
                                        'avg_rating': 'Ср. рейтинг'},
                            )
                            fig_so.update_layout(margin=dict(t=10, b=10, l=10, r=10),
                                                 height=280, yaxis_tickformat='.0%',
                                                 paper_bgcolor='white', plot_bgcolor='white')
                            st.plotly_chart(fig_so, use_container_width=True)
                            st.caption(f"ρ = {rho_occ:+.3f}, p = {p_occ:.3f}")

                    with cq2:
                        st.markdown("*Тональность ↔ Популярность*")
                        if len(q_metrics) >= 5:
                            rho_pop, p_pop = spearmanr(q_metrics['sentiment'], q_metrics['кол_оценок'])
                            fig_sp = px.scatter(
                                q_metrics, x='sentiment', y='кол_оценок',
                                hover_name='quest_name', color='avg_rating',
                                color_continuous_scale=['#dc2626', '#f59e0b', '#16a34a'],
                                labels={'sentiment': 'Sentiment',
                                        'кол_оценок': 'Кол-во оценок',
                                        'avg_rating': 'Ср. рейтинг'},
                                log_y=True,
                            )
                            fig_sp.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=280,
                                                 paper_bgcolor='white', plot_bgcolor='white')
                            st.plotly_chart(fig_sp, use_container_width=True)
                            st.caption(f"ρ = {rho_pop:+.3f}, p = {p_pop:.3f}")

                    st.markdown("---")

                    st.markdown("**Примеры негативных отзывов**")
                    neg_reviews = rev_filt[
                        rev_filt['category'].isin(['negative', 'strongly_negative'])
                    ].sort_values('score_norm').head(8)

                    if len(neg_reviews) == 0:
                        st.info("В текущей выборке нет негативных отзывов.")
                    else:
                        for _, row in neg_reviews.iterrows():
                            with st.expander(
                                f"**{row['quest_name']}** · sentiment {row['score_norm']:+.2f} · "
                                f"рейтинг {int(row['rating']) if pd.notna(row['rating']) else '—'}★"
                            ):
                                if row.get('neg_words'):
                                    st.markdown(f"**Негативные маркеры:** `{row['neg_words']}`")
                                if row.get('pos_words'):
                                    st.markdown(f"**Позитивные маркеры:** `{row['pos_words']}`")
                                st.markdown(f"**Текст:**")
                                st.write(str(row['text']))

                    with st.expander("Методология sentiment-анализа"):
                        st.markdown("""
                        **Словарный подход с лемматизацией:**

                        1. **Нормализация:** текст → нижний регистр, токенизация (только кириллица/латиница).
                        2. **Лемматизация:** через pymorphy3 (формы → начальная: «понравилось» → «понравиться»).
                        3. **Словарь:** ~150 позитивных лемм (вес +1/+2), ~70 негативных (вес −1/−2),
                           специализирован под квест-тематику.
                        4. **Учёт контекста:** отрицания инвертируют знак, усилители ×1.5, смягчители ×0.5.
                        5. **Нормализация score:** к диапазону [−1, +1].
                        6. **Категоризация:** 5 категорий с порогами ±0.1 и ±0.5.

                        **Валидация:** сильная монотонная зависимость sentiment от звёзд
                        (2★ → −0.40, 5★ → +0.65) подтверждает корректность.
                        """)

