import altair as alt
import pandas as pd
import streamlit as st

from ui.sidebar import render_sidebar
from ui.tab_profile import render_tab_profile
from ui.tab_tapering import render_tab_tapering
from ui.tab_simulation import render_tab_simulation

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
weight, user_vo2, user_vlamax, selected_sport, sim_method = render_sidebar(db_data)

# --- DEFINIZIONE TABS ---
tab1, tab2, tab3 = st.tabs(["Dati & Upload", "Simulazione Gara", "Analisi Avanzata"])

# =============================================================================
# TAB 1: PROFILO & METABOLISMO
# =============================================================================
with tab1:
    render_tab_profile(db_data, weight, user_vo2, user_vlamax, selected_sport, sim_method)

# =============================================================================
# TAB 2: DIARIO IBRIDO
# =============================================================================
with tab2:
    render_tab_tapering()

# =============================================================================
# TAB 3: SIMULAZIONE GARA & STRATEGIA (PULITA)
# =============================================================================
with tab3:
    render_tab_simulation(sim_method, create_cutoff_line)
