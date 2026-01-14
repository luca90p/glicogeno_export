import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import math
import matplotlib.pyplot as plt

# Import moduli locali puliti
import logic
import utils
from data_models import (
    Sex, TrainingStatus, SportType, DietType, FatigueState, 
    SleepQuality, MenstrualPhase, ChoMixType, Subject, IntakeMode
)

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Glycogen Simulator", layout="wide")
st.title("Glycogen Simulator")
st.markdown("""
Applicazione avanzata per la modellazione delle riserve di glicogeno.
""")

# --- INIZIALIZZAZIONE MEMORIA VOLATILE ---
if 'user_profile' not in st.session_state:
    st.session_state['user_profile'] = {
        'weight': 70.0, 'vo2': 55.0, 'ftp': 250, 'fat': 12.0, 'sport': 'Cycling'
    }
# Alias comodo per lettura (la scrittura va fatta su st.session_state direttamnte se serve persistere)
db_data = st.session_state['user_profile']

if 'use_lab_data' not in st.session_state:
    st.session_state.update({'use_lab_data': False, 'lab_cho_mean': 0, 'lab_fat_mean': 0})

# --- FUNZIONI GRAFICHE HELPER ---
def create_cutoff_line(cutoff_time):
    return alt.Chart(pd.DataFrame({'x': [cutoff_time]})).mark_rule(
        color='black', strokeDash=[5, 5], size=2
    ).encode(
        x='x',
        tooltip=[alt.Tooltip('x', title='Stop Assunzione (min)')]
    )

# ==============================================================================================
# --- SIDEBAR: CONFIGURAZIONE MOTORE ---
# ==============================================================================================
with st.sidebar:
    st.header("1. Profilo Atleta")
    
    # 1. SCELTA DISCIPLINA
    saved_sport_idx = 0 if db_data['sport'] == "Cycling" else 1
    
    sport_mode = st.radio(
        "Disciplina:", 
        ["Ciclismo", "Corsa"], 
        index=saved_sport_idx,
        horizontal=True
    )
    
    if "Corsa" in sport_mode:
        selected_sport = SportType.RUNNING
        st.markdown("---")
        st.markdown("**Logica Motore Corsa**")
        # Semplificato: Solo scelta intensità per calcoli calorie
        run_logic_mode = st.radio(
            "Input Intensità:",
            ["Fisiologica (Heart Rate)", "Meccanica (Passo/Watt)"],
            help="Definisce come interpretare i dati di input."
        )
        sim_method = "PHYSIOLOGICAL" if "Fisiologica" in run_logic_mode else "MECHANICAL"
    else:
        selected_sport = SportType.CYCLING
        sim_method = "MECHANICAL" # Ciclismo è sempre meccanico (Watt)

    st.markdown("---")
    
    # 2. PESO
    weight = st.number_input("Peso Corporeo (kg)", 40.0, 120.0, 70.0, step=0.5)

    st.divider()

    st.header("2. Fisiologia")
    
    # MODALITÀ DI INPUT: SOLO MANUALE
    st.caption("Inserisci il tuo VO2max (da test o smartwatch).")
    
    # Recuperiamo il valore di default dalla sessione o usiamo 55
    default_vo2 = float(db_data.get('vo2', 55.0))
    
    user_vo2 = st.number_input(
        "VO2max (ml/kg/min)", 
        min_value=30.0, 
        max_value=90.0, 
        value=default_vo2, 
        step=1.0,
        help="Volume massimo di ossigeno consumato. Se non lo conosci, 45-50 è un valore medio per amatori, 60+ per atleti allenati."
    )

    # VLaMax fittizia (non più usata nei calcoli, ma richiesta dalla struttura dati Subject)
    user_vlamax = 0.5 
    
    st.markdown("---")

# --- DEFINIZIONE TABS ---
tab1, tab2, tab3 = st.tabs(["Dati & Upload", "Simulazione Gara", "Analisi Avanzata"])

# =============================================================================
# TAB 1: PROFILO & METABOLISMO
# =============================================================================
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("1. Parametri Antropometrici")
        height = st.slider("Altezza (cm)", 150, 210, 187, 1)
        default_bf = float(st.session_state['user_profile']['fat'])
        bf_input = st.slider("Massa Grassa (%)", 4.0, 30.0, default_bf, 0.5, key="body_fat_pct_input")
        bf = bf_input / 100.0
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        # Opzioni Extra
        with st.expander("Opzioni Avanzate"):
            use_smm = st.checkbox("Usa Massa Muscolare (SMM) misurata")
            muscle_mass_input = st.number_input("SMM [kg]", 10.0, 60.0, 37.4, 0.1) if use_smm else None
            
            use_creatine = st.checkbox("Usa Creatina")
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                m_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = m_map[st.selectbox("Fase Ciclo", list(m_map.keys()))]

        st.markdown("---")
        st.subheader("2. Soglie Operative")
        st.caption("Questi valori servono per scalare l'intensità (IF) e le Zone.")
        
        # Input Soglie (FTP/HR)
        c_ftp, c_hr = st.columns(2)
        ftp_watts = c_ftp.number_input("FTP Ciclismo (Watt)", 100, 600, 265, step=5)
        thr_hr = c_hr.number_input("Soglia Anaerobica (BPM)", 100, 220, 170, step=1)
        max_hr = st.number_input("FC Max (BPM)", 100, 230, 185, step=1)
        
        # Salva soglie in session state
        st.session_state.update({'ftp_watts_input': ftp_watts, 'thr_hr_input': thr_hr, 'max_hr_input': max_hr})

        # --- SEZIONE: PROFILO METABOLICO (LAB) ---
        st.markdown("---")
        with st.expander("Profilo Metabolico (Test Laboratorio)", expanded=False):
            st.info("Inserisci i dati dal test del gas (Metabolimetro) per personalizzare i consumi.")
            active_lab = st.checkbox("Attiva Profilo Metabolico Personalizzato", value=st.session_state.get('use_lab_data', False))
            
            if active_lab:
                st.caption("Carica il file raw esportato dal metabolimetro (.csv, .xlsx, .txt).")
                upl_file = st.file_uploader("Carica Report Metabolimetro", type=['csv', 'xlsx', 'txt'])
                
                if upl_file:
                    df_raw, avail_metrics, err = utils.parse_metabolic_report(upl_file)
                    
                    if df_raw is not None:
                        st.success("✅ File decodificato con successo!")
                        sel_metric = avail_metrics[0]
                        
                        if len(avail_metrics) > 1:
                            st.markdown("##### 📐 Seleziona il Riferimento (Asse X)")
                            def_idx = avail_metrics.index('Watt') if 'Watt' in avail_metrics else 0
                            sel_metric = st.radio("Scegli su cosa basare le curve:", avail_metrics, index=def_idx, horizontal=True)
                        
                        # Preparazione DataFrame Curve
                        df_curve = df_raw.copy()
                        df_curve['Intensity'] = df_curve[sel_metric]
                        df_curve = df_curve[df_curve['Intensity'] > 0].sort_values('Intensity').reset_index(drop=True)
                        
                        # Visualizzazione Grafico Anteprima
                        c_chart = alt.Chart(df_curve).mark_line(point=True).encode(
                            x=alt.X('Intensity', title=f'Intensità ({sel_metric})'), 
                            y='CHO', color=alt.value('blue'), tooltip=['Intensity', 'CHO', 'FAT']
                        ) + alt.Chart(df_curve).mark_line(point=True).encode(
                            x='Intensity', y='FAT', color=alt.value('orange')
                        )
                        st.altair_chart(c_chart, use_container_width=True)
                        
                        # Salvataggio in Session State
                        st.session_state['use_lab_data'] = True
                        st.session_state['metabolic_curve'] = df_curve
                        st.info(f"Curve salvate basate su: **{sel_metric}**")
                    else:
                        st.error(f"Errore nel parsing del file: {err}")
            else:
                st.session_state['use_lab_data'] = False
                st.session_state['metabolic_curve'] = None

        # --- CREAZIONE OGGETTO SUBJECT ---
        calculated_conc = logic.get_concentration_from_vo2max(user_vo2)
        
        subject = Subject(
            weight_kg=weight, 
            height_cm=height, 
            body_fat_pct=bf, 
            sex=s_sex,
            glycogen_conc_g_kg=calculated_conc, 
            sport=selected_sport,
            uses_creatine=use_creatine, 
            menstrual_phase=s_menstrual,
            
            # DATI DAL MOTORE FISIOLOGICO
            vo2_max=user_vo2,
            vlamax=user_vlamax,
            vo2max_absolute_l_min=(user_vo2 * weight) / 1000,
            
            muscle_mass_kg=muscle_mass_input
        )
        
        tank_data = logic.calculate_tank(subject)
        st.session_state['base_subject_struct'] = subject
        st.session_state['base_tank_data'] = tank_data

    with col_res:
        st.subheader("Riepilogo Profilo")
        
        m1, m2 = st.columns(2)
        m1.metric("VO2max", f"{user_vo2:.1f}")
        m2.metric("FTP / Soglia", f"{ftp_watts if selected_sport==SportType.CYCLING else thr_hr}")
        
        st.divider()
        st.subheader("Analisi Tank (Serbatoio)")
        max_cap = tank_data['max_capacity_g']
        c1, c2, c3 = st.columns(3)
        c1.metric("Capacità Totale", f"{int(max_cap)} g")
        c2.metric("Energia", f"{int(max_cap*4.1)} kcal")
        c3.metric("Massa Attiva", f"{tank_data['active_muscle_kg']:.1f} kg")
        st.progress(1.0)
        
        st.markdown("### Zone di Allenamento")
        t_cyc, t_run = st.tabs(["Ciclismo (Power)", "Corsa (Heart Rate)"])
        with t_cyc:
            st.table(pd.DataFrame(utils.calculate_zones_cycling(ftp_watts)))
        with t_run:
            st.table(pd.DataFrame(utils.calculate_zones_running_hr(thr_hr)))

# =============================================================================
# TAB 2: DIARIO IBRIDO
# =============================================================================
with tab2:
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
    
    from data_models import GlycogenState
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
        if row['day_offset'] >= -2: c1.markdown("🔴 *Load*")
        
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
            
            if new_type == "Ciclismo" and user_ftp > 0: calc_if = new_val / user_ftp
            elif new_type == "Corsa/Altro" and user_thr > 0: calc_if = new_val / user_thr
            
            if calc_if > 0: ac_2.caption(f"IF: **{calc_if:.2f}**")
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
        k3.metric("Fegato Start Gara", f"{int(final_tank['liver_glycogen_g'])} g", 
                  delta="Attenzione" if final_tank['liver_glycogen_g'] < 80 else "Ottimale", delta_color="normal")

# =============================================================================
# TAB 3: SIMULAZIONE GARA & STRATEGIA (PULITA)
# =============================================================================
with tab3:
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
            
            if fname.endswith('.zwo'):
                series, dur_calc, w_calc, hr_calc = utils.parse_zwo_file(uploaded_file, target_ftp, target_thresh_hr, subj.sport)
                if series:
                    duration = dur_calc
                    st.success(f"✅ ZWO: {dur_calc} min")
                    
                    if subj.sport == SportType.CYCLING:
                        intensity_series = [val * target_ftp for val in series]
                        val = w_calc * target_ftp
                        params = {'mode': 'cycling', 'avg_watts': val, 'np_watts': val, 'ftp_watts': target_ftp, 'efficiency': 22.0}
                    else:
                        intensity_series = [val * target_thresh_hr for val in series]
                        val = hr_calc * target_thresh_hr
                        params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': target_thresh_hr}
            
            elif fname.endswith('.fit'):
                fit_series, fit_dur, fit_avg_w, fit_avg_hr, fit_np, fit_dist, fit_elev, fit_work, fit_clean_df, graphs_data = utils.parse_fit_file_wrapper(uploaded_file, subj.sport)
                
                if fit_clean_df is not None:
                    intensity_series = fit_series
                    duration = fit_dur
                    fit_df = fit_clean_df
                    st.success("✅ File FIT elaborato")
                    
                    k1, k2 = st.columns(2)
                    k1.metric("Durata", f"{fit_dur} min")
                    
                    if subj.sport == SportType.CYCLING:
                        k2.metric("Avg Power", f"{int(fit_avg_w)} W")
                        val = int(fit_avg_w)
                        vi_input = fit_np / fit_avg_w if fit_avg_w > 0 else 1.0
                        params = {'mode': 'cycling', 'avg_watts': val, 'np_watts': fit_np, 'ftp_watts': target_ftp, 'efficiency': 22.0}
                    else:
                        k2.metric("Avg HR", f"{int(fit_avg_hr)} bpm")
                        val = int(fit_avg_hr)
                        # Logica running semplificata: se c'è watt usa watt, se no cardio
                        if fit_avg_w > 0:
                             params = {'mode': 'running', 'avg_watts': fit_avg_w, 'ftp_watts': target_ftp}
                        else:
                             params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': target_thresh_hr}

        if not file_loaded:
            duration = st.number_input("Durata (min)", 60, 900, 180, step=10)
            
            if subj.sport == SportType.CYCLING:
                val = st.slider("Potenza Media (Watt)", 50, 600, 200, 5)
                vi_input = st.slider("Variabilità (VI)", 1.0, 1.3, 1.0, 0.01)
                np_val = val * vi_input
                if vi_input > 1.0: st.caption(f"NP Stimata: **{int(np_val)} W**")
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
                    if t == 0 or (t > 0 and t % intake_interval == 0): num_intakes += 1
                
                total_grams = num_intakes * cho_unit
                if duration > 0: cho_h = total_grams / (duration / 60)
                else: cho_h = 0
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

        st.markdown("---")
        st.markdown("#### Ossidazione Lipidica (Tasso Orario)")
        chart_fat = alt.Chart(df_sim).mark_line(color='#FFC107', strokeWidth=3).encode(
            x=alt.X('Time (min)'),
            y=alt.Y('Ossidazione Lipidica (g)', title='Grassi (g/h)'),
            tooltip=['Time (min)', 'Ossidazione Lipidica (g)']
        ).properties(height=250)
        st.altair_chart(chart_fat + cutoff_line, use_container_width=True)

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









