import streamlit as st

from data_models import SportType


def render_sidebar(db_data):
    """Render sidebar profile inputs and return core selections."""
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
            sim_method = "MECHANICAL"  # Ciclismo è sempre meccanico (Watt)

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

    return weight, user_vo2, user_vlamax, selected_sport, sim_method

