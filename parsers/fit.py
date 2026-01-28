import math
import numpy as np
import pandas as pd
import fitparse

from calculations.normalized_power import calculate_normalized_power
from data_models import SportType


def process_fit_data(fit_file_object):
    """
    Legge file .FIT, normalizza, pulisce pause e restituisce DataFrame.
    """
    try:
        fit_file_object.seek(0)
        fitfile = fitparse.FitFile(fit_file_object)
    except Exception as e:
        return None, f"Errore file FIT: {e}"

    data_list = []
    for record in fitfile.get_messages("record"):
        r_data = {}
        for field in record:
            r_data[field.name] = field.value
        if 'timestamp' in r_data:
            data_list.append(r_data)

    if not data_list:
        return None, "Nessun dato record."

    df_raw = pd.DataFrame(data_list)
    df_raw = df_raw.set_index('timestamp').sort_index()

    # Normalizzazione Temporale (1s)
    if not df_raw.empty:
        full_idx = pd.date_range(start=df_raw.index.min(), end=df_raw.index.max(), freq='1s')
        # Forward fill limitato (max 5 sec) per evitare di inventare dati in pause lunghe
        df_raw = df_raw.reindex(full_idx).ffill(limit=5).fillna(0)

    col_map = {
        'power': ['power', 'accumulated_power'],
        'speed': ['enhanced_speed', 'speed'],
        'altitude': ['enhanced_altitude', 'altitude'],
        'heart_rate': ['heart_rate'],
        'cadence': ['cadence'],
        'distance': ['distance']
    }

    df_clean = pd.DataFrame(index=df_raw.index)
    for std, alts in col_map.items():
        for alt in alts:
            if alt in df_raw.columns:
                df_clean[std] = df_raw[alt]
                break

    # Conversione Speed m/s -> km/h
    if 'speed' in df_clean.columns:
        if df_clean['speed'].max() < 100:
            df_clean['speed_kmh'] = df_clean['speed'] * 3.6
        else:
            df_clean['speed_kmh'] = df_clean['speed']
    else:
        df_clean['speed_kmh'] = 0

    # --- ALGORITMO FILTRO PAUSE MIGLIORATO ---
    # 1. Soglia velocità: < 2.5 km/h è pausa (camminata lenta/fermo)
    # 2. Potenza zero: Se power=0 E speed < 5 km/h per più di 10s -> Pausa
    # 3. Cadenza zero: Se cadenza=0 E speed < 5 km/h -> Pausa (Ciclismo)
    is_stopped = df_clean['speed_kmh'] < 2.5

    # Maschera finale
    df_final = df_clean[~is_stopped].copy()

    # Ricalcolo asse temporale continuo (Moving Time)
    df_final['moving_time_min'] = np.arange(len(df_final)) / 60.0

    return df_final, None


def parse_fit_file_wrapper(uploaded_file, sport_type):
    """
    Estrae dati dal FIT file.
    Ritorna:
    1. simulation_series (lista valori per simulazione, es. 1 al secondo)
    2. statistiche scalari (duration, avg, etc)
    3. graphs_data (Dizionario con liste per grafici alta risoluzione)
    """
    df, error = process_fit_data(uploaded_file)
    if error or df is None or df.empty:
        # Ritorna anche graphs_data vuoto alla fine
        return [], 0, 0, 0, 0, 0, 0, 0, None, {}

    # --- 1. Statistiche Scalari ---
    avg_power = df['power'].mean() if 'power' in df.columns else 0
    avg_hr = df['heart_rate'].mean() if 'heart_rate' in df.columns else 0
    norm_power = calculate_normalized_power(df) if 'power' in df.columns else 0
    total_duration_min = math.ceil(len(df) / 60)

    dist = 0
    if 'distance' in df.columns:
        dist = (df['distance'].max() - df['distance'].min()) / 1000.0
    elif 'speed' in df.columns:
        dist = (df['speed'].mean() * 3.6 * (total_duration_min / 60))

    elev_gain = 0
    col_alt = 'enhanced_altitude' if 'enhanced_altitude' in df.columns else 'altitude'
    if col_alt in df.columns:
        deltas = df[col_alt].diff()
        elev_gain = deltas[deltas > 0].sum()

    work_kj = (avg_power * len(df)) / 1000 if 'power' in df.columns else 0

    # --- 2. Preparazione Dati Grafici (Sampling ogni 10s) ---
    df_active = df.reset_index(drop=True)
    # Raggruppa ogni 10 secondi per non appesantire i grafici
    df_res = df_active.groupby(df_active.index // 10).mean()

    graphs_data = {
        'x_dist': [], 'pace': [], 'lap_pace': [],
        'hr': [], 'cadence': [], 'elevation': []
    }

    # Assi comuni
    if 'distance' in df_res.columns:
        graphs_data['x_dist'] = (df_res['distance'] / 1000.0).tolist()
    else:
        # Fallback temporale se manca distanza
        graphs_data['x_dist'] = (df_res.index * 10 / 60).tolist()  # asse X in minuti

    # Dati specifici
    if 'heart_rate' in df_res.columns:
        graphs_data['hr'] = df_res['heart_rate'].fillna(0).tolist()

    if 'cadence' in df_res.columns:
        graphs_data['cadence'] = df_res['cadence'].fillna(0).tolist()

    if col_alt in df_res.columns:
        graphs_data['elevation'] = df_res[col_alt].fillna(0).tolist()

    # Logica specifica Corsa (Passo min/km)
    if sport_type == SportType.RUNNING and 'speed' in df_res.columns:
        s = df_res['speed'].replace(0, np.nan)  # Evita div zero
        p = (1000 / s) / 60
        # Filtra passi assurdi (es. camminata lenta > 20 min/km)
        graphs_data['pace'] = [x if (x > 0 and x < 20) else None for x in p.tolist()]

        # Calcolo Lap Pace (Media su ogni Km)
        if 'distance' in df_active.columns:
            # Crea una colonna 'km_split' sui dati raw
            df_active['split_km'] = (df_active['distance'] / 1000).astype(int)
            # Calcola velocità media per quello split
            split_speeds = df_active.groupby('split_km')['speed'].mean()
            # Mappa sui dati resamplati
            res_split_idx = (df_res['distance'] / 1000).astype(int)
            lap_pace_dict = ((1000 / split_speeds) / 60).to_dict()
            graphs_data['lap_pace'] = [lap_pace_dict.get(k, 0) for k in res_split_idx]

    # --- 3. Serie per Simulazione (Sampling 1 min o 1 sec) ---
    # Per la simulazione metabolica, preferiamo dati al secondo ma qui restituiamo la lista
    # Se logic.simulate accetta liste lunghe, passiamo df['power'] o df['heart_rate'] raw.
    target_col = 'power' if (sport_type == SportType.CYCLING and 'power' in df.columns) else 'heart_rate'

    simulation_series = []
    if target_col in df.columns:
        simulation_series = df[target_col].fillna(0).tolist()

    return simulation_series, total_duration_min, avg_power, avg_hr, norm_power, dist, elev_gain, work_kj, df, graphs_data
