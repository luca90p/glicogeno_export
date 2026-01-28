import altair as alt
import pandas as pd
import streamlit as st

import logic
import utils
from data_models import MenstrualPhase, Sex, SportType, Subject


def render_tab_profile(db_data, weight, user_vo2, user_vlamax, selected_sport, sim_method):
    """Render Tab 1 (Profilo & Metabolismo) and persist base subject/tank."""
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
        with st.expander("🧬 Profilo Metabolico (Test Laboratorio)", expanded=False):
            st.info("Inserisci i dati dal test del gas (Metabolimetro) per personalizzare i consumi.")
            active_lab = st.checkbox("Attiva Profilo Metabolico Personalizzato", value=st.session_state.get('use_lab_data', False))

            if active_lab:
                st.caption("Carica il file raw esportato dal metabolimetro (.csv, .xlsx, .txt).")
                upl_file = st.file_uploader("Carica Report Metabolimetro", type=['csv', 'xlsx', 'txt'])

                if upl_file:
                    df_raw, avail_metrics, err = utils.parse_metabolic_report(upl_file)

                    if df_raw is not None:
                        st.success("✅ File decodificato con successo!")

                        # --- NUOVA LOGICA: SELEZIONE ESPLICITA METRICA ---
                        st.markdown("##### 📐 Seleziona il Riferimento (Asse X)")
                        st.caption("Quale parametro guida il consumo nella tua prova?")

                        # Seleziona la metrica principale (es. HR, Watt, Speed)
                        sel_metric = st.radio(
                            "Metrica Disponibile:",
                            avail_metrics,
                            index=0,
                            horizontal=True,
                            help="Se scegli HR, la simulazione userà la frequenza cardiaca del file FIT. Se scegli Watt, userà la potenza."
                        )

                        # Preparazione DataFrame Curve
                        df_curve = df_raw.copy()
                        # Rinomina la colonna scelta in 'Intensity' per standardizzare
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
                        st.session_state['curve_metric'] = sel_metric  # <--- SALVIAMO LA SCELTA UTENTE
                        st.info(f"Curve salvate basate su: **{sel_metric}**")
                    else:
                        st.error(f"Errore nel parsing del file: {err}")
            else:
                st.session_state['use_lab_data'] = False
                st.session_state['metabolic_curve'] = None
                st.session_state['curve_metric'] = None

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

    return subject, tank_data, sim_method

