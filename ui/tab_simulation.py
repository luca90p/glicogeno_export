import altair as alt
import pandas as pd
import streamlit as st

import logic
import utils
from data_models import ChoMixType, IntakeMode, SportType


def render_tab_simulation(sim_method, create_cutoff_line):
    """Render Tab 3 (Simulazione Gara & Strategia)."""
    if 'tank_data' not in st.session_state:
        st.stop()

    tank_base = st.session_state['tank_data']
    subj = st.session_state['subject_struct']

    # --- OVERRIDE MODE ---
    st.markdown("### Modalità Test / Override")
    enable_override = st.checkbox("Abilita Override Livello Iniziale", value=False)

    if enable_override:
        max_cap = tank_base['max_capacity_g']
        st.warning(f"Modalità Test Attiva. Max: {int(max_cap)}g")
        force_pct = st.slider("Forza Livello (%)", 0, 120, 100, 5)
        tank = tank_base.copy()
        tank['muscle_glycogen_g'] = (max_cap - 100) * (force_pct / 100.0)
        tank['liver_glycogen_g'] = 100 * (force_pct / 100.0)
        tank['actual_available_g'] = tank['muscle_glycogen_g'] + tank['liver_glycogen_g']
        start_total = tank['actual_available_g']
        st.metric("Start Glicogeno", f"{int(start_total)} g")
    else:
        tank = tank_base
        start_total = tank['actual_available_g']
        st.info(f"**Start Glicogeno (da Tab 2):** {int(start_total)}g")

    c_s1, c_s2, c_s3 = st.columns(3)

    # --- 1. PROFILO SFORZO ---
    with c_s1:
        st.markdown("### 1. Profilo Sforzo")
        uploaded_file = st.file_uploader("Carica File (.fit, .zwo)", type=['zwo', 'fit', 'gpx', 'csv'])
        intensity_series = None
        fit_df = None
        params = {}
        vi_input = 1.0
        file_loaded = False

        target_thresh_hr = st.session_state.get('thr_hr_input', 170)
        target_ftp = st.session_state.get('ftp_watts_input', 250)

        if uploaded_file:
            file_loaded = True
            fname = uploaded_file.name.lower()

            if fname.endswith('.fit'):
                fit_series, fit_dur, fit_avg_w, fit_avg_hr, fit_np, fit_dist, fit_elev, fit_work, fit_clean_df, graphs_data = utils.parse_fit_file_wrapper(uploaded_file, subj.sport)

                if fit_clean_df is not None:
                    duration = fit_dur
                    fit_df = fit_clean_df
                    st.success("✅ File FIT elaborato")

                    # --- NUOVA LOGICA: ALLINEAMENTO METABOLICO ---
                    # Recupera le impostazioni dal Tab 1
                    lab_active = st.session_state.get('use_lab_data', False)
                    curve_metric_pref = st.session_state.get('curve_metric', None)  # es. 'HR', 'Watt', 'Speed'

                    forced_source_col = None
                    forced_metric_name = None

                    # Se l'utente ha una curva metabolica attiva, cerchiamo di usare quella metrica nel FIT
                    if lab_active and curve_metric_pref:
                        if curve_metric_pref == 'HR' and 'heart_rate' in fit_clean_df.columns:
                            forced_source_col = 'heart_rate'
                            forced_metric_name = 'Heart Rate (BPM)'
                        elif curve_metric_pref == 'Watt' and 'power' in fit_clean_df.columns:
                            forced_source_col = 'power'
                            forced_metric_name = 'Power (Watt)'
                        elif curve_metric_pref == 'Speed' and 'speed' in fit_clean_df.columns:
                            forced_source_col = 'speed'  # fitparse restituisce m/s di solito, check utils
                            forced_metric_name = 'Speed'

                    # Estrazione Serie Temporale (Resampled 1min)
                    df_resampled = fit_clean_df.resample('1min').mean()

                    if forced_source_col:
                        # ABBIAMO TROVATO IL MATCH! Usiamo la metrica della curva.
                        st.info(f"🔄 **Allineamento Attivo:** Simulazione basata su **{forced_metric_name}** come da Profilo Lab.")

                        # Gestione specifica Speed (di solito m/s -> km/h per matchare Lab)
                        if forced_source_col == 'speed':
                            intensity_series = (df_resampled[forced_source_col] * 3.6).fillna(0).tolist()
                            val = int(fit_clean_df['speed'].mean() * 3.6)
                            params = {'mode': 'running', 'avg_watts': val}  # Hack: passiamo speed come avg_watts
                        else:
                            intensity_series = df_resampled[forced_source_col].fillna(0).tolist()
                            val = int(df_resampled[forced_source_col].mean())

                            if forced_source_col == 'heart_rate':
                                params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': target_thresh_hr}
                            else:
                                params = {'mode': 'cycling', 'avg_watts': val, 'np_watts': val, 'ftp_watts': target_ftp, 'efficiency': 22.0}

                    else:
                        # FALLBACK: Comportamento Standard (Se non c'è lab o non c'è match)
                        k1, k2 = st.columns(2)
                        k1.metric("Durata", f"{fit_dur} min")

                        if subj.sport == SportType.CYCLING:
                            k2.metric("Avg Power", f"{int(fit_avg_w)} W")
                            intensity_series = fit_series  # Watt
                            val = int(fit_avg_w)
                            vi_input = fit_np / fit_avg_w if fit_avg_w > 0 else 1.0
                            params = {'mode': 'cycling', 'avg_watts': val, 'np_watts': fit_np, 'ftp_watts': target_ftp, 'efficiency': 22.0}
                        else:
                            k2.metric("Avg HR", f"{int(fit_avg_hr)} bpm")
                            val = int(fit_avg_hr)
                            if fit_avg_w > 0:  # Stryd
                                intensity_series = df_resampled['power'].fillna(0).tolist()
                                params = {'mode': 'running', 'avg_watts': fit_avg_w, 'ftp_watts': target_ftp}
                            else:
                                intensity_series = df_resampled['heart_rate'].fillna(0).tolist()
                                params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': target_thresh_hr}

            elif fname.endswith('.zwo'):
                series, dur_calc, w_calc, hr_calc = utils.parse_zwo_file(uploaded_file, target_ftp, target_thresh_hr, subj.sport)
                if series:
                    duration = dur_calc
                    st.success(f"✅ ZWO: {dur_calc} min")
                    intensity_series = [val * target_ftp if subj.sport == SportType.CYCLING else val * target_thresh_hr for val in series]
                    val = w_calc * target_ftp
                    params = {'mode': 'cycling' if subj.sport == SportType.CYCLING else 'running', 'avg_watts': val, 'threshold_hr': target_thresh_hr}

        if not file_loaded:
            duration = st.number_input("Durata (min)", 60, 900, 180, step=10)

            if subj.sport == SportType.CYCLING:
                val = st.slider("Potenza Media (Watt)", 50, 600, 200, 5)
                vi_input = st.slider("Variabilità (VI)", 1.0, 1.3, 1.0, 0.01)
                np_val = val * vi_input
                if vi_input > 1.0:
                    st.caption(f"NP Stimata: **{int(np_val)} W**")
                params = {'mode': 'cycling', 'avg_watts': val, 'np_watts': np_val, 'ftp_watts': target_ftp, 'efficiency': 22.0}
            else:
                if sim_method == "PHYSIOLOGICAL":
                    st.info(" **Input: Cardio (BPM)**")
                    val = st.slider("FC Media (BPM)", 80, 210, 155, 1)
                    params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': target_thresh_hr}
                else:
                    st.info(" **Input: Velocità / Passo**")
                    speed_kmh = st.slider("Velocità (km/h)", 6.0, 22.0, 12.0, 0.1)
                    pace_dec = 60 / speed_kmh
                    pace_min = int(pace_dec)
                    pace_sec = int((pace_dec - pace_min) * 60)
                    st.metric("Passo Stimato", f"{pace_min}:{pace_sec:02d} /km")
                    params = {'mode': 'running', 'avg_watts': speed_kmh}

    # --- 2. STRATEGIA NUTRIZIONALE ---
    with c_s2:
        st.markdown("### 2. Strategia Nutrizionale")
        intake_mode_sel = st.radio("Modalità Assunzione:", ["Discretizzata (Gel/Barrette)", "Continuativa (Liquid/Sorsi)"])
        intake_mode_enum = IntakeMode.DISCRETE if intake_mode_sel.startswith("Discret") else IntakeMode.CONTINUOUS

        mix_sel = st.selectbox("Mix Carboidrati", list(ChoMixType), format_func=lambda x: x.label)
        intake_cutoff = st.slider("Stop Assunzione prima del termine (min)", 0, 60, 20)

        cho_h = 0
        cho_unit = 0

        if intake_mode_enum == IntakeMode.DISCRETE:
            c_u1, c_u2 = st.columns(2)
            cho_unit = c_u1.number_input("Grammi CHO per Unità", 10, 100, 25)
            intake_interval = c_u2.number_input("Intervallo Assunzione (min)", 10, 120, 40, step=5)

            if intake_interval > 0:
                feeding_window = duration - intake_cutoff
                num_intakes = 0
                for t in range(0, int(feeding_window) + 1):
                    if t == 0 or (t > 0 and t % intake_interval == 0):
                        num_intakes += 1

                total_grams = num_intakes * cho_unit
                if duration > 0:
                    cho_h = total_grams / (duration / 60)
                else:
                    cho_h = 0
                st.info(f"Rateo Effettivo Gara: **{int(cho_h)} g/h**")
        else:
            cho_h = st.slider("Target Intake (g/h)", 0, 120, 60, step=5)
            cho_unit = 30
            st.caption("Assunzione continua.")

    # --- 3. MOTORE METABOLICO ---
    with c_s3:
        st.markdown("### 3. Motore Metabolico")
        curve_data = st.session_state.get('metabolic_curve', None)
        use_lab_active = st.session_state.get('use_lab_data', False)

        if use_lab_active and curve_data is not None:
            st.success("✅ **Curva Metabolica (Lab)**")
            st.caption("Usa dati diretti da test del gas.")
            tau = 20
            risk_thresh = 30
            crossover_val = 75
        else:
            # UNICA OPZIONE RIMASTA: Modello Standard
            st.info("ℹ️ **Modello Teorico (Statistico)**")
            crossover_val = st.slider("Crossover Point (% Soglia)", 50, 90, 75, help="Intensità dove i CHO superano i grassi.")

            tau = st.slider("Costante Assorbimento (Tau)", 5, 60, 20)
            risk_thresh = st.slider("Soglia Tolleranza GI (g)", 10, 100, 30)

    # --- GRAFICO FIT ---
    if fit_df is not None:
        with st.expander("Analisi Dettagliata File FIT", expanded=True):
            st.altair_chart(utils.create_fit_plot(fit_df), use_container_width=True)

    # --- SELEZIONE MODALITÀ SIMULAZIONE ---
    st.markdown("---")
    sim_mode = st.radio("Modalità Simulazione:", ["Simulazione Manuale (Verifica Tattica)", "Calcolatore Strategia Minima (Reverse)"], horizontal=True)
    cutoff_line = create_cutoff_line(duration - intake_cutoff)

    if sim_mode == "Simulazione Manuale (Verifica Tattica)":

        # CHIAMATA PULITA AL NUOVO LOGIC.PY (Senza parametri Mader/Running method)
        df_sim, stats_sim = logic.simulate_metabolism(
            tank, duration, cho_h, cho_unit,
            crossover_val if not use_lab_active else 75,
            tau, subj, params,
            mix_type_input=mix_sel,
            intensity_series=intensity_series,
            metabolic_curve=curve_data if use_lab_active else None,
            intake_mode=intake_mode_enum,
            intake_cutoff_min=intake_cutoff,
            variability_index=vi_input
        )
        df_sim['Scenario'] = 'Strategia Integrata'
        df_sim['Residuo Totale'] = df_sim['Residuo Muscolare'] + df_sim['Residuo Epatico']

        df_no, _ = logic.simulate_metabolism(
            tank, duration, 0, cho_unit,
            crossover_val if not use_lab_active else 75,
            tau, subj, params,
            mix_type_input=mix_sel,
            intensity_series=intensity_series,
            metabolic_curve=curve_data if use_lab_active else None,
            intake_mode=intake_mode_enum,
            intake_cutoff_min=intake_cutoff,
            variability_index=vi_input
        )
        df_no['Scenario'] = 'Riferimento (Digiuno)'
        df_no['Residuo Totale'] = df_no['Residuo Muscolare'] + df_no['Residuo Epatico']

        # --- DASHBOARD RISULTATI ---
        st.markdown("---")
        st.subheader("Analisi Cinetica e Substrati")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Intensity Factor (IF)", f"{stats_sim['intensity_factor']:.2f}", help="Basato su NP se disponibile")
        c2.metric("RER Stimato (RQ)", f"{stats_sim['avg_rer']:.2f}")
        c3.metric("Ripartizione Substrati", f"{int(stats_sim['cho_pct'])}% CHO", f"{100-int(stats_sim['cho_pct'])}% FAT", delta_color="off")
        c4.metric("Glicogeno Residuo", f"{int(stats_sim['final_glycogen'])} g", delta=f"{int(stats_sim['final_glycogen'] - start_total)} g")

        st.markdown("---")
        m1, m2, m3 = st.columns(3)
        m1.metric("Uso Glicogeno Muscolare", f"{int(stats_sim['total_muscle_used'])} g")
        m2.metric("Uso Glicogeno Epatico", f"{int(stats_sim['total_liver_used'])} g")
        m3.metric("Uso CHO Esogeno", f"{int(stats_sim['total_exo_used'])} g")

        st.markdown("### Bilancio Energetico: Richiesta vs. Fonti di Ossidazione")

        # 1. Calcoliamo la colonna del Totale (Somma di tutte le fonti)
        df_sim['Consumo Totale (g/h)'] = (
            df_sim['Glicogeno Epatico (g)'] +
            df_sim['Carboidrati Esogeni (g)'] +
            df_sim['Ossidazione Lipidica (g)'] +
            df_sim['Glicogeno Muscolare (g)']
        )

        # Preparazione dati per l'area stack
        df_melt = df_sim.melt('Time (min)', value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
        order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
        colors = ['#B71C1C', '#1E88E5', '#FFCA28', '#EF5350']

        # A. Grafico a Aree (Le fonti)
        chart_stack = alt.Chart(df_melt).mark_area().encode(
            x='Time (min)', y='g/h',
            color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors), sort=order),
            tooltip=['Time (min)', 'Fonte', 'g/h']
        )

        # B. Linea del Totale (Il contorno superiore)
        chart_total = alt.Chart(df_sim).mark_line(color='black', strokeDash=[3,3], opacity=0.8, strokeWidth=2).encode(
            x='Time (min)',
            y='Consumo Totale (g/h)',
            tooltip=[alt.Tooltip('Time (min)'), alt.Tooltip('Consumo Totale (g/h)', format='.1f')]
        )

        # Uniamo tutto
        st.altair_chart((chart_stack + chart_total + cutoff_line).interactive(), use_container_width=True)

        # INIEZIONE BPM REALI (Se disponibili dal FIT)
        if fit_df is not None and 'heart_rate' in fit_df.columns:
            # Resample della HR originale del FIT per matchare i minuti della simulazione
            hr_resampled = fit_df.resample('1min')['heart_rate'].mean().fillna(0)
            # Allinea le lunghezze
            sim_len = len(df_sim)
            hr_list = hr_resampled.tolist()[:sim_len]
            # Se la simulazione è più lunga del fit (es. manual override), pad con 0
            if len(hr_list) < sim_len:
                hr_list += [0] * (sim_len - len(hr_list))
            df_sim['BPM_Activity'] = hr_list
        else:
            df_sim['BPM_Activity'] = 0

        # DASHBOARD
        st.markdown("---")
        st.subheader("Analisi Cinetica")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("IF", f"{stats_sim['intensity_factor']:.2f}")
        c2.metric("RER", f"{stats_sim['avg_rer']:.2f}")
        c3.metric("CHO/FAT", f"{int(stats_sim['cho_pct'])}% / {100-int(stats_sim['cho_pct'])}%")
        c4.metric("Glicogeno Finale", f"{int(stats_sim['final_glycogen'])} g", delta=f"{int(stats_sim['final_glycogen'] - start_total)} g")

        # --- GRAFICO 1: Ossidazione Lipidica + BPM ---
        st.markdown("### 📉 Ossidazione Lipidica vs Heart Rate")
        with st.expander("Vedi Dettaglio", expanded=True):
            base = alt.Chart(df_sim).encode(x=alt.X('Time (min)', title='Tempo (min)'))

            line_fat = base.mark_line(color='#FFC107', strokeWidth=3).encode(
                y=alt.Y('Ossidazione Lipidica (g)', title='Grassi (g/h)', axis=alt.Axis(titleColor='#FFC107')),
                tooltip=['Time (min)', 'Ossidazione Lipidica (g)']
            )

            line_hr = base.mark_line(color='red', strokeDash=[2,2], opacity=0.5).encode(
                y=alt.Y('BPM_Activity', title='Heart Rate (BPM)', axis=alt.Axis(titleColor='red')),
                tooltip=['Time (min)', 'BPM_Activity']
            )

            st.altair_chart(alt.layer(line_fat, line_hr).resolve_scale(y='independent').interactive(), use_container_width=True)

        # --- GRAFICO 2: Bilancio Carboidrati Completo + BPM ---
        st.markdown("### 📊 Dettaglio Carboidrati & Intensità")

        df_melt = df_sim.melt('Time (min)', value_vars=['Carboidrati Esogeni (g)', 'Glicogeno Epatico (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
        # Ordine Stack: Exo (base) -> Liver -> Muscle (top)
        order = ['Carboidrati Esogeni (g)', 'Glicogeno Epatico (g)', 'Glicogeno Muscolare (g)']
        colors = ['#1E88E5', '#BF360C', '#EF5350']

        # Base Chart
        base_cho = alt.Chart(df_sim).encode(x='Time (min)')

        # 1. Area Stacked (Le fonti)
        chart_stack = alt.Chart(df_melt).mark_area(opacity=0.85).encode(
            x='Time (min)', y='g/h',
            color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors)),
            tooltip=['Time (min)', 'Fonte', 'g/h']
        )

        # 2. Linea Consumo CHO Totale (Muscolo+Fegato+Exo) - NO GRASSI
        df_sim['Total_CHO_Burn'] = df_sim['Glicogeno Muscolare (g)'] + df_sim['Glicogeno Epatico (g)'] + df_sim['Carboidrati Esogeni (g)']
        chart_total_cho = base_cho.mark_line(color='black', strokeWidth=2).encode(
            y='Total_CHO_Burn', tooltip=[alt.Tooltip('Total_CHO_Burn', title='Totale CHO (g/h)')]
        )

        # 3. Linea BPM (Asse Destro)
        chart_hr_overlay = base_cho.mark_line(color='red', strokeDash=[2,2], opacity=0.5).encode(
            y=alt.Y('BPM_Activity', axis=alt.Axis(title='BPM', titleColor='red')),
            tooltip=['BPM_Activity']
        )

        # Layering: Stack + Linea Totale su asse SX, HR su asse DX
        combined_cho = alt.layer(chart_stack + chart_total_cho, chart_hr_overlay).resolve_scale(y='independent')

        st.altair_chart(combined_cho.interactive(), use_container_width=True)

        st.markdown("---")
        st.markdown("#### Confronto Riserve Nette")

        reserve_fields = ['Residuo Muscolare', 'Residuo Epatico']
        reserve_colors = ['#E57373', '#B71C1C']

        df_reserve_sim = df_sim.melt('Time (min)', value_vars=reserve_fields, var_name='Tipo', value_name='Grammi')
        df_reserve_no = df_no.melt('Time (min)', value_vars=reserve_fields, var_name='Tipo', value_name='Grammi')

        max_y = start_total * 1.05
        zones_df = pd.DataFrame({
            'Start': [max_y * 0.35, max_y * 0.15, 0],
            'End': [max_y * 1.10, max_y * 0.35, max_y * 0.15],
            'Color': ['#66BB6A', '#FFA726', '#EF5350']
        })

        def create_reserve_stacked_chart(df_data, title):
            bg = alt.Chart(zones_df).mark_rect(opacity=0.15).encode(
                y=alt.Y('Start', scale=alt.Scale(domain=[0, max_y]), axis=None),
                y2='End', color=alt.Color('Color', scale=None)
            )
            area = alt.Chart(df_data).mark_area().encode(
                x='Time (min)',
                y=alt.Y('Grammi', stack='zero', title='Residuo (g)'),
                color=alt.Color('Tipo', scale=alt.Scale(domain=reserve_fields, range=reserve_colors)),
                order=alt.Order('Tipo', sort='ascending'),
                tooltip=['Time (min)', 'Tipo', 'Grammi']
            )
            return (bg + area + cutoff_line).properties(title=title, height=300)

        c_strat, c_digi = st.columns(2)
        with c_strat:
            st.altair_chart(create_reserve_stacked_chart(df_reserve_sim, "Con Integrazione"), use_container_width=True)
        with c_digi:
            st.altair_chart(create_reserve_stacked_chart(df_reserve_no, "Digiuno"), use_container_width=True)

        st.markdown("---")
        st.markdown("#### Analisi Gut Load")
        base = alt.Chart(df_sim).encode(x='Time (min)')
        area_gut = base.mark_area(color='#795548', opacity=0.6).encode(y=alt.Y('Gut Load', title='Accumulo (g)'), tooltip=['Gut Load'])
        rule = alt.Chart(pd.DataFrame({'y': [risk_thresh]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
        chart_gi = alt.layer(area_gut, rule, cutoff_line).properties(height=350)
        st.altair_chart(chart_gi, use_container_width=True)

        st.markdown("---")
        st.subheader("Analisi Criticità & Timing")

        liver_bonk = df_sim[df_sim['Residuo Epatico'] <= 0]
        muscle_bonk = df_sim[df_sim['Residuo Muscolare'] <= 20]

        bonk_time = None
        cause = None

        if not liver_bonk.empty:
            bonk_time = liver_bonk['Time (min)'].iloc[0]
            cause = "Esaurimento Epatico (Ipoglicemia)"
        if not muscle_bonk.empty:
            t_muscle = muscle_bonk['Time (min)'].iloc[0]
            if bonk_time is None or t_muscle < bonk_time:
                bonk_time = t_muscle
                cause = "Esaurimento Muscolare (Gambe Vuote)"

        c_b1, c_b2 = st.columns([2, 1])
        with c_b1:
            if bonk_time:
                st.error(f"⚠️ **CRITICITÀ RILEVATA AL MINUTO {bonk_time}**")
                st.write(f"Causa Primaria: **{cause}**")
            else:
                st.success("✅ **STRATEGIA SOSTENIBILE**")
        with c_b2:
            if bonk_time:
                st.metric("Tempo Limite", f"{bonk_time} min", delta="Bonk!", delta_color="inverse")
            else:
                st.metric("Buffer Energetico", "Sicuro")

        st.markdown("---")
        st.markdown("### Cronotabella Operativa")
        if intake_mode_enum == IntakeMode.DISCRETE and cho_h > 0 and cho_unit > 0:
            schedule = []
            current_time = intake_interval
            total_ingested = 0
            if intake_interval > 0:
                total_ingested += cho_unit
                schedule.append({"Minuto": 0, "Azione": f"Assumere 1 unità ({cho_unit}g CHO)", "Totale Ingerito": f"{total_ingested}g"})
                while current_time <= (duration - intake_cutoff):
                    total_ingested += cho_unit
                    schedule.append({
                        "Minuto": current_time,
                        "Azione": f"Assumere 1 unità ({cho_unit}g CHO)",
                        "Totale Ingerito": f"{total_ingested}g"
                    })
                    current_time += intake_interval
            if schedule:
                st.table(pd.DataFrame(schedule))
                st.info(f"Portare **{len(schedule)}** unità.")
            else:
                st.warning("Nessuna assunzione prevista.")

        elif intake_mode_enum == IntakeMode.CONTINUOUS and cho_h > 0:
            st.info(f"Bere continuativamente: **{cho_h} g/ora** di carboidrati.")
            effective_duration = max(0, duration - intake_cutoff)
            total_needs = (effective_duration/60) * cho_h
            st.write(f"**Totale Gara:** preparare borracce con **{int(total_needs)} g** totali.")

    else:
        # --- CALCOLO REVERSE STRATEGY ---
        st.subheader("Calcolatore Strategia Minima")
        st.markdown("Il sistema calcolerà l'apporto di carboidrati minimo necessario per terminare la gara senza crisi.")

        # FIX IMPORTANTE: Se il lab data è disattivato, forziamo None
        curve_to_use = curve_data if use_lab_active else None

        if st.button("Calcola Fabbisogno Minimo"):
            # CORREZIONE: Rimosso riferimento a 'use_mader_sim'
            with st.spinner("Ottimizzazione modello in corso..."):
                # CORREZIONE: Rimossi argomenti 'use_mader' e 'running_method' che non esistono più in logic.py
                opt_intake = logic.calculate_minimum_strategy(
                    tank, duration, subj, params,
                    curve_to_use,
                    mix_sel, intake_mode_enum, intake_cutoff,
                    variability_index=vi_input,
                    intensity_series=intensity_series
                )

            if opt_intake is not None:
                if opt_intake == 0:
                    st.success("### ✅ Nessuna integrazione necessaria (0 g/h)")
                    st.caption("Le tue riserve sono sufficienti per coprire la durata a questa intensità.")

                else:
                    st.success(f"### ✅ Strategia Minima: {opt_intake} g/h")
                    if intake_mode_enum == IntakeMode.DISCRETE and cho_unit > 0:
                        interval_min = int(60 / (opt_intake / cho_unit))
                        st.info(f"Assumere **1 unità da {cho_unit}g** ogni **{interval_min} minuti**")
                    else:
                        st.info(f"Bere **{opt_intake}g** di carboidrati per ogni ora.")

                # --- 2. ESEGUIAMO LE DUE SIMULAZIONI PER IL CONFRONTO ---

                # Scenario A: Il Crollo (0 g/h)
                # CORREZIONE: Rimossi argomenti obsoleti use_mader/running_method
                df_zero, stats_zero = logic.simulate_metabolism(
                    tank, duration, 0, 0, 70, 20, subj, params,
                    mix_type_input=mix_sel,
                    metabolic_curve=curve_to_use,
                    intake_mode=intake_mode_enum, intake_cutoff_min=intake_cutoff,
                    variability_index=vi_input,
                    intensity_series=intensity_series
                )

                # Scenario B: Il Salvataggio (opt_intake g/h)
                # CORREZIONE: Rimossi argomenti obsoleti use_mader/running_method
                df_opt, stats_opt = logic.simulate_metabolism(
                    tank, duration, opt_intake, cho_unit if cho_unit > 0 else 25, 70, 20, subj, params,
                    mix_type_input=mix_sel,
                    metabolic_curve=curve_to_use,
                    intake_mode=intake_mode_enum, intake_cutoff_min=intake_cutoff,
                    variability_index=vi_input,
                    intensity_series=intensity_series
                )

                st.markdown("---")
                st.subheader("⚔️ Confronto Impatto: Senza vs. Con Integrazione")

                col_bad, col_good = st.columns(2)

                max_y_scale = start_total * 1.1

                # Funzione helper locale per grafici confronto
                def plot_enhanced_scenario(df, stats, title, is_bad_scenario):
                    df_melt = df.melt('Time (min)', value_vars=['Residuo Muscolare', 'Residuo Epatico'], var_name='Riserva', value_name='Grammi')
                    colors_range = ['#EF9A9A', '#C62828'] if is_bad_scenario else ['#A5D6A7', '#2E7D32']
                    bg_color = '#FFEBEE' if is_bad_scenario else '#F1F8E9'

                    zones = pd.DataFrame([
                        {'y': 0, 'y2': 20, 'c': '#FFCDD2'},
                        {'y': 20, 'y2': max_y_scale, 'c': bg_color}
                    ])

                    bg = alt.Chart(zones).mark_rect(opacity=0.5).encode(
                        y=alt.Y('y', scale=alt.Scale(domain=[0, max_y_scale]), title='Glicogeno (g)'),
                        y2='y2',
                        color=alt.Color('c', scale=None)
                    )

                    area = alt.Chart(df_melt).mark_area(opacity=0.85).encode(
                        x='Time (min)',
                        y=alt.Y('Grammi', stack=True),
                        color=alt.Color('Riserva', scale=alt.Scale(domain=['Residuo Muscolare', 'Residuo Epatico'], range=colors_range), legend=alt.Legend(orient='bottom', title=None)),
                        tooltip=['Time (min)', 'Riserva', 'Grammi']
                    )

                    layers = [bg, area, cutoff_line]

                    if is_bad_scenario:
                        bonk_row = df[df['Residuo Epatico'] <= 0]
                        if not bonk_row.empty:
                            bonk_time = bonk_row.iloc[0]['Time (min)']
                            rule = alt.Chart(pd.DataFrame({'x': [bonk_time]})).mark_rule(color='red', strokeDash=[4,4], size=3).encode(x='x')
                            text = alt.Chart(pd.DataFrame({'x': [bonk_time], 'y': [max_y_scale*0.5], 't': ['BONK!']})).mark_text(
                                align='left', dx=5, color='#B71C1C', size=16, fontWeight='bold'
                            ).encode(x='x', y='y', text='t')
                            layers.extend([rule, text])
                    else:
                        final_res = int(stats['final_glycogen'])
                        final_time = df['Time (min)'].max()
                        text = alt.Chart(pd.DataFrame({'x': [final_time], 'y': [final_res], 't': [f'✅ {final_res}g']})).mark_text(
                            align='right', dy=-15, color='#1B5E20', size=16, fontWeight='bold'
                        ).encode(x='x', y='y', text='t')
                        layers.append(text)

                    return alt.layer(*layers).properties(title=title, height=320)

                with col_bad:
                    st.altair_chart(plot_enhanced_scenario(df_zero, stats_zero, "🔴 SCENARIO DIGIUNO (Fallimento)", True), use_container_width=True)
                    final_liv = df_zero['Residuo Epatico'].iloc[-1]
                    if final_liv <= 0:
                        st.error(f"**CROLLO METABOLICO**")
                        st.caption("Il serbatoio epatico si è svuotato. Prestazione compromessa.")
                    else:
                        st.warning("Riserve al limite.")

                with col_good:
                    st.altair_chart(plot_enhanced_scenario(df_opt, stats_opt, f"🟢 SCENARIO STRATEGIA ({opt_intake} g/h)", False), use_container_width=True)
                    saved_grams = int(stats_opt['final_glycogen'] - stats_zero['final_glycogen'])
                    st.success(f"**SALVATAGGIO: +{saved_grams}g**")
                    st.caption(f"L'integrazione ha preservato {saved_grams}g di glicogeno extra, garantendo l'arrivo.")

                # --- Dettagli Tecnici ---
                with st.expander("Dettagli Tecnici Avanzati"):
                    st.write(f"**Dispendio Totale:** {int(stats_opt['kcal_total_h'])} kcal")
                    st.write(f"**CHO Ossidati Totali:** {int(df_opt['Carboidrati Esogeni (g)'].sum()/60 + stats_opt['total_liver_used'] + stats_opt['total_muscle_used'])} g")
                    st.write(f"**Di cui da integrazione:** {int(df_opt['Carboidrati Esogeni (g)'].sum()/60)} g")
                    st.write(f"**Grassi Ossidati:** {int(stats_opt['fat_total_g'])} g")

            else:
                st.error("**IMPOSSIBILE FINIRE LA GARA**")
                st.markdown(f"""
                Anche assumendo il massimo teorico ({120} g/h), le tue riserve si esauriscono prima della fine.

                **Consigli:**
                1. **Riduci l'intensità**: Abbassa i Watt/FC medi o il target FTP.
                2. **Aumenta il Tapering**: Cerca di partire con il serbatoio più pieno (Tab 2).
                """)

