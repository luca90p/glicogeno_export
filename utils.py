import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
import fitparse
import altair as alt
from data_models import SportType

from calculations.normalized_power import calculate_normalized_power as _calculate_normalized_power
from parsers.fit import process_fit_data as _process_fit_data
from parsers.fit import parse_fit_file_wrapper as _parse_fit_file_wrapper
from parsers.metabolic import parse_metabolic_report as _parse_metabolic_report
from parsers.metabolic import resample_to_unit_intervals as _resample_to_unit_intervals
from parsers.metabolic import apply_smoothing as _apply_smoothing
from parsers.metabolic import find_header_row_index as _find_header_row_index
from parsers.zwo import parse_zwo_file as _parse_zwo_file
from plots.fit_altair import create_fit_plot as _create_fit_plot

# ==============================================================================
# MODULO CALCOLO POTENZA NORMALIZZATA (NP)
# ==============================================================================
def calculate_normalized_power(df):
    return _calculate_normalized_power(df)

# ==============================================================================
# MODULO FIT PARSER & PLOTTING
# ==============================================================================

def process_fit_data(fit_file_object):
    """
    Legge file .FIT, normalizza, pulisce pause e restituisce DataFrame.
    """
    return _process_fit_data(fit_file_object)

def create_fit_plot(df):
    """Genera grafico ALTAIR a 4 pannelli: Power, HR, Cadence, Altitude."""
    return _create_fit_plot(df)

# Assicurati di importare l'enum SportType se lo usi, o usa stringhe
# from constants import SportType 

def parse_fit_file_wrapper(uploaded_file, sport_type):
    """
    Estrae dati dal FIT file.
    Ritorna:
    1. simulation_series (lista valori per simulazione, es. 1 al secondo)
    2. statistiche scalari (duration, avg, etc)
    3. graphs_data (Dizionario con liste per grafici alta risoluzione)
    """
    return _parse_fit_file_wrapper(uploaded_file, sport_type)
# ==============================================================================
# PARSER METABOLICO "FULL STACK"
# 1. Parsing -> 2. Smoothing -> 3. Resampling Unitario
# ==============================================================================
def parse_metabolic_report(uploaded_file):
    return _parse_metabolic_report(uploaded_file)

# ==============================================================================
# LOGICA DI RESAMPLING (Cruciale per "Niente Salti")
# ==============================================================================
def resample_to_unit_intervals(df, x_col):
    """
    Crea una Lookup Table densa interpolando i dati.
    - Watt/HR: Step 1 (es. 100, 101, 102...)
    - Speed: Step 0.1 (es. 10.0, 10.1, 10.2...)
    """
    return _resample_to_unit_intervals(df, x_col)

# ==============================================================================
# LOGICA SMOOTHING (Pulizia Rumore e Binning)
# ==============================================================================
def apply_smoothing(df, metrics):
    return _apply_smoothing(df, metrics)

def find_header_row_index(df_temp):
    return _find_header_row_index(df_temp)
#================================================================================================
# --- ZWO ---
#================================================================================================
def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    return _parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type)

# --- ZONE ---
def calculate_zones_cycling(ftp):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(ftp*p)} W"} for i, p in enumerate([0.55, 0.75, 0.90, 1.05, 1.20])]
def calculate_zones_running_hr(thr):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(thr*p)} bpm"} for i, p in enumerate([0.85, 0.89, 0.94, 0.99, 1.02])]



















