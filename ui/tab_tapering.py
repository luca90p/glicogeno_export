import altair as alt
import pandas as pd
import streamlit as st

import logic
from data_models import GlycogenState


def render_tab_tapering():
    """Render Tab 2 (Diario Ibrido) and update session state."""
    if 'base_tank_data' not in st.session_state:
        st.warning("Completa prima il Tab 1.")
        st.stop()

    subj_base = st.session_state['base_subject_struct']
    user_ftp = st.session_state.get('ftp_watts_input', 250)
    user_thr = st.session_state.get('thr_hr_input', 170)

    st.subheader("🗓️ Diario di Avvicinamento (Timeline Oraria)")

    # --- SETUP CALENDARIO & DURATA ---
    c_cal1, c_cal2, c_cal3 = st.columns([1, 1, 1])

    race_date = c_cal1.date_input("Data Evento Target", value=pd.Timestamp.today() + pd.Timedelta(days=7))
    num_days_taper = c_cal2.slider("Durata Diario (Giorni)", 2, 7, 7)

    gly_states = list(GlycogenState)
    start_label = f"Condizione a -{num_days_taper}gg"
    sel_state = c_cal3.selectbox(start_label, gly_states, format_func=lambda x: x.label, index=2)

    # --- DEFAULT SCHEDULE ---
    with st.expander("⚙️ Orari Standard (Default)", expanded=False):
        d_c1, d_c2 = st.columns(2)
        def_sleep_start = d_c1.time_input("Orario Sonno (Inizio)", value=pd.to_datetime("23:00").time())
        def_sleep_end = d_c2.time_input("Orario Sveglia", value=pd.to_datetime("07:00").time())
        def_work_start = pd.to_datetime("18:00").time()

    st.markdown("---")

    # --- GESTIONE STATO ---
    if "tapering_data" not in st.session_state:
        st.session_state["tapering_data"] = []

    # Reset/Resize logica
    if len(st.session_state["tapering_data"]) != num_days_taper:
        new_data = []
        for i in range(num_days_taper, 0, -1):
            day_offset = -i
            d_date = race_date + pd.Timedelta(days=day_offset)
            new_data.append({
                "day_offset": day_offset,
                "date_obj": d_date,
                "type": "Riposo", "val": 0, "dur": 0, "cho": 300,
                "sleep_quality": "Sufficiente (6-7h)",
                "sleep_start": def_sleep_start, "sleep_end": def_sleep_end, "workout_start": def_work_start
            })
        st.session_state["tapering_data"] = new_data
        st.rerun()
    else:
        for i, row in enumerate(st.session_state["tapering_data"]):
            day_offset = - (num_days_taper - i)
            row['date_obj'] = race_date + pd.Timedelta(days=day_offset)
            row['day_offset'] = day_offset

    # --- TABELLA INPUT (RAGGRUPPATA) ---
    cols_layout = [0.8, 2.8, 1.0, 1.4]
    h1, h2, h3, h4 = st.columns(cols_layout)
    h1.markdown("##### Data")
    h2.markdown("##### Attività (Tipo, Durata, Intensità, Start)")
    h3.markdown("##### Nutrizione")
    h4.markdown("##### Riposo")

    sleep_opts_map = {"Ottimale (>7h)": 1.0, "Sufficiente (6-7h)": 0.95, "Insufficiente (<6h)": 0.85}
    type_opts = ["Riposo", "Ciclismo", "Corsa/Altro"]

    input_result_data = []

    for i, row in enumerate(st.session_state["tapering_data"]):
        st.markdown(f"<div style='border-top: 1px solid #eee; margin-bottom: 5px;'></div>", unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(cols_layout)

        # --- COL 1: DATA ---
        c1.write(f"**{row['date_obj'].strftime('%d/%m')}**")
        c1.caption(f"{row['date_obj'].strftime('%a')}")
        if row['day_offset'] >= -2:
            c1.markdown("🔴 *Load*")

        # --- COL 2: GRUPPO ATTIVITÀ ---
        act_idx = type_opts.index(row['type']) if row['type'] in type_opts else 0
        new_type = c2.selectbox("Tipo Attività", type_opts, index=act_idx, key=f"t_{i}", label_visibility="collapsed")

        calc_if = 0.0
        new_dur = 0
        new_val = 0
        new_w_start = row.get('workout_start', def_work_start)

        if new_type != "Riposo":
            ac_1, ac_2, ac_3 = c2.columns([1, 1, 1])
            new_dur = ac_1.number_input("Minuti", 0, 400, row['dur'], step=15, key=f"d_{i}", help="Durata")

            help_lbl = "Watt" if new_type == "Ciclismo" else "Bpm"
            new_val = ac_2.number_input(help_lbl, 0, 500, row['val'], step=10, key=f"v_{i}", help="Intensità Media")

            new_w_start = ac_3.time_input("Start", new_w_start, key=f"ws_{i}", help="Orario Inizio Allenamento")

            if new_type == "Ciclismo" and user_ftp > 0:
                calc_if = new_val / user_ftp
            elif new_type == "Corsa/Altro" and user_thr > 0:
                calc_if = new_val / user_thr

            if calc_if > 0:
                ac_2.caption(f"IF: **{calc_if:.2f}**")
        else:
            c2.caption("Nessuna attività fisica prevista.")

        # --- COL 3: NUTRIZIONE ---
        new_cho = c3.number_input("CHO Totali (g)", 0, 2000, row['cho'], step=50, key=f"c_{i}")
        kg_rel = new_cho / subj_base.weight_kg
        c3.caption(f"**{kg_rel:.1f}** g/kg")

        # --- COL 4: RIPOSO ---
        sq_idx = list(sleep_opts_map.keys()).index(row['sleep_quality']) if row['sleep_quality'] in sleep_opts_map else 0
        new_sq = c4.selectbox("Qualità Sonno", list(sleep_opts_map.keys()), index=sq_idx, key=f"sq_{i}", label_visibility="collapsed")

        sl_1, sl_2 = c4.columns(2)
        new_s_start = sl_1.time_input("Inizio", row.get('sleep_start', def_sleep_start), key=f"ss_{i}", label_visibility="collapsed")
        new_s_end = sl_2.time_input("Fine", row.get('sleep_end', def_sleep_end), key=f"se_{i}", label_visibility="collapsed")

        st.session_state["tapering_data"][i].update({
            "type": new_type, "val": new_val, "dur": new_dur, "cho": new_cho,
            "sleep_start": new_s_start, "sleep_end": new_s_end, "workout_start": new_w_start,
            "sleep_quality": new_sq
        })

        input_result_data.append({
            "date_obj": row['date_obj'],
            "type": new_type, "val": new_val, "duration": new_dur, "calculated_if": calc_if,
            "cho_in": new_cho, "sleep_factor": sleep_opts_map[new_sq],
            "sleep_start": new_s_start, "sleep_end": new_s_end, "workout_start": new_w_start
        })

    st.markdown("---")

    # --- SIMULAZIONE ---
    if st.button("Calcola Traiettoria Oraria", type="primary"):
        df_hourly, final_tank = logic.calculate_hourly_tapering(subj_base, input_result_data, start_state=sel_state)

        st.session_state['tank_data'] = final_tank
        st.session_state['subject_struct'] = subj_base

        st.markdown("### Evoluzione Oraria Riserve (Timeline)")

        df_melt = df_hourly.melt('Timestamp', value_vars=['Muscolare', 'Epatico'], var_name='Riserva', value_name='Grammi')
        c_range = ['#43A047', '#FB8C00']

        chart = alt.Chart(df_melt).mark_area(opacity=0.8).encode(
            x=alt.X('Timestamp', title='Data/Ora', axis=alt.Axis(format='%d/%m %H:%M')),
            y=alt.Y('Grammi', stack=True),
            color=alt.Color('Riserva', scale=alt.Scale(domain=['Muscolare', 'Epatico'], range=c_range)),
            tooltip=['Timestamp', 'Riserva', 'Grammi']
        ).properties(height=350).interactive()

        st.altair_chart(chart, use_container_width=True)

        k1, k2, k3 = st.columns(3)
        pct = final_tank['fill_pct']
        k1.metric("Riempimento Finale", f"{pct:.1f}%")
        k2.metric("Muscolo Start Gara", f"{int(final_tank['muscle_glycogen_g'])} g")
        k3.metric(
            "Fegato Start Gara", f"{int(final_tank['liver_glycogen_g'])} g",
            delta="Attenzione" if final_tank['liver_glycogen_g'] < 80 else "Ottimale", delta_color="normal"
        )

