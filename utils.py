import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
import fitparse
import altair as alt
from data_models import SportType

# ==============================================================================
# MODULO CALCOLO POTENZA NORMALIZZATA (NP)
# ==============================================================================
def calculate_normalized_power(df):
    if 'power' not in df.columns: return 0
    rolling_pwr = df['power'].rolling(window=30, min_periods=1).mean()
    return (rolling_pwr ** 4).mean() ** 0.25

# ==============================================================================
# MODULO FIT PARSER & PLOTTING
# ==============================================================================

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
        for field in record: r_data[field.name] = field.value
        if 'timestamp' in r_data: data_list.append(r_data)

    if not data_list: return None, "Nessun dato record."

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

def create_fit_plot(df):
    """Genera grafico ALTAIR a 4 pannelli: Power, HR, Cadence, Altitude."""
    # Resampling per performance grafica
    plot_df = df.reset_index()
    if len(plot_df) > 5000: plot_df = plot_df.iloc[::10, :] # Downsample più aggressivo per velocità
    
    base = alt.Chart(plot_df).encode(x=alt.X('moving_time_min', title='Tempo in Movimento (min)'))
    charts = []
    
    # 1. POTENZA
    if 'power' in df.columns and df['power'].max() > 0:
        c_pwr = base.mark_area(color='#FF4B4B', opacity=0.6, line=True).encode(
            y=alt.Y('power', title='Watt'),
            tooltip=['moving_time_min', 'power']
        ).properties(height=150, title="Potenza")
        charts.append(c_pwr)
    
    # 2. CARDIO
    if 'heart_rate' in df.columns and df['heart_rate'].max() > 0:
        c_hr = base.mark_line(color='#A020F0').encode(
            y=alt.Y('heart_rate', title='BPM', scale=alt.Scale(zero=False)),
            tooltip=['moving_time_min', 'heart_rate']
        ).properties(height=150, title="Frequenza Cardiaca")
        charts.append(c_hr)
        
    # 3. ALTIMETRIA (Nuovo!)
    if 'altitude' in df.columns:
        # Area grigia stile Strava
        min_alt = df['altitude'].min()
        c_alt = base.mark_area(color='#90A4AE', opacity=0.4, line={'color':'#546E7A'}).encode(
            y=alt.Y('altitude', title='Metri', scale=alt.Scale(domain=[min_alt, df['altitude'].max()])),
            tooltip=['moving_time_min', 'altitude']
        ).properties(height=150, title="Profilo Altimetrico")
        charts.append(c_alt)

    # 4. CADENZA
    if 'cadence' in df.columns and df['cadence'].max() > 0:
        c_cad = base.transform_filter(alt.datum.cadence > 0).mark_circle(color='#00FF00', size=5, opacity=0.2).encode(
            y=alt.Y('cadence', title='RPM'),
            tooltip=['moving_time_min', 'cadence']
        ).properties(height=100, title="Cadenza")
        charts.append(c_cad)

    if charts:
        return alt.vconcat(*charts).resolve_scale(x='shared')
    else:
        return alt.Chart(pd.DataFrame({'T':['Nessun dato valido']})).mark_text().encode(text='T')

import pandas as pd
import numpy as np
import math

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
        dist = (df['speed'].mean() * 3.6 * (total_duration_min/60))
        
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
        graphs_data['x_dist'] = (df_res.index * 10 / 60).tolist() # asse X in minuti

    # Dati specifici
    if 'heart_rate' in df_res.columns:
        graphs_data['hr'] = df_res['heart_rate'].fillna(0).tolist()
        
    if 'cadence' in df_res.columns:
        graphs_data['cadence'] = df_res['cadence'].fillna(0).tolist()
        
    if col_alt in df_res.columns:
        graphs_data['elevation'] = df_res[col_alt].fillna(0).tolist()

    # Logica specifica Corsa (Passo min/km)
    if sport_type == SportType.RUNNING and 'speed' in df_res.columns:
         s = df_res['speed'].replace(0, np.nan) # Evita div zero
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
# ==============================================================================
# PARSER METABOLICO UNIVERSALE (CERCA GLI HEADER)
# ==============================================================================
def parse_metabolic_report(uploaded_file):
    """
    Scansiona il file per trovare la riga di intestazione corretta.
    Estrae CHO, FAT e le metriche di intensità (Watt, FC, Speed).
    """
    filename = uploaded_file.name.lower()
    df = None
    
    try:
        uploaded_file.seek(0)
        
        # 1. RILEVAMENTO HEADER
        # Leggiamo le prime 500 righe come testo per trovare dove inizia la tabella
        content = uploaded_file.getvalue().decode('latin-1', errors='replace')
        all_lines = content.splitlines()
        
        header_idx = -1
        sep = ',' # Default per CSV standard
        
        # Parole chiave che identificano la riga di intestazione
        keywords = ['CHO', 'FAT', 'FC', 'WR', 'V\'O2', 'RER']
        
        for i, line in enumerate(all_lines[:500]): 
            # Contiamo quante parole chiave sono presenti nella riga
            line_upper = line.upper()
            matches = sum(1 for k in keywords if k in line_upper)
            
            if matches >= 3: # Se ne troviamo almeno 3, è l'header
                header_idx = i
                # Rileviamo il separatore (conta virgole vs punti e virgola)
                if line.count(';') > line.count(','): sep = ';'
                break
        
        if header_idx == -1:
            return None, [], "Intestazione non trovata. Assicurati che il file contenga CHO, FAT, FC."

        # 2. CARICAMENTO DATAFRAME
        uploaded_file.seek(0)
        if filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file, header=header_idx)
        else:
            df = pd.read_csv(uploaded_file, sep=sep, skiprows=header_idx, engine='python')

        if df is None or df.empty:
            return None, [], "File vuoto dopo la lettura."

        # 3. PULIZIA NOMI COLONNE
        # Rimuoviamo spazi e convertiamo in maiuscolo per facilitare la ricerca
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        clean_df = pd.DataFrame()
        
        # Funzione helper per cercare colonne con sinonimi
        def get_col_data(synonyms):
            for col in df.columns:
                # Match esatto (priorità) o parziale
                if col in synonyms:
                    return col
            # Se non trova match esatti, cerca parziali
            for col in df.columns:
                for syn in synonyms:
                    if syn in col: return col
            return None

        # Funzione conversione numeri (gestisce virgole europee)
        def to_float(col_name):
            if not col_name: return None
            s = df[col_name].astype(str).str.replace(',', '.', regex=False)
            # Rimuove caratteri non numerici strani
            s = pd.to_numeric(s, errors='coerce')
            return s

        # --- MAPPATURA METRICHE ---
        
        # 1. Substrati (Fondamentali)
        c_cho = get_col_data(['CHO', 'QCHO', 'CARBOHYDRATES'])
        c_fat = get_col_data(['FAT', 'QFAT', 'LIPIDS'])
        
        clean_df['CHO'] = to_float(c_cho)
        clean_df['FAT'] = to_float(c_fat)
        
        clean_df.dropna(subset=['CHO', 'FAT'], inplace=True)
        if clean_df.empty: return None, [], "Dati CHO/FAT non validi o assenti."

        # 2. Intensità (Watt, FC, Speed)
        available_metrics = []
        
        # WATT (Cerca 'WR' specifico per il tuo file, poi 'WATT')
        c_watt = get_col_data(['WR', 'WATT', 'POWER', 'POW', 'LOAD'])
        s_watt = to_float(c_watt)
        if s_watt is not None and s_watt.max() > 10: # Filtro rumore
            clean_df['Watt'] = s_watt
            available_metrics.append('Watt')

        # HEART RATE (Cerca 'FC' specifico per il tuo file, poi 'HR')
        c_hr = get_col_data(['FC', 'HR', 'BPM', 'HEART'])
        s_hr = to_float(c_hr)
        if s_hr is not None and s_hr.max() > 40:
            clean_df['HR'] = s_hr
            available_metrics.append('HR')

        # SPEED (Cerca 'V' specifico per il tuo file, poi 'SPEED')
        # Nota: 'V' da solo è ambiguo, controlliamo che sia proprio 'V' o 'SPEED'
        c_spd = None
        if 'V' in df.columns: c_spd = 'V' # Priorità al nome esatto del tuo file
        else: c_spd = get_col_data(['SPEED', 'VELOCITY', 'KM/H'])
        
        s_spd = to_float(c_spd)
        if s_spd is not None and s_spd.max() > 2: # Se max > 2 km/h
            clean_df['Speed'] = s_spd
            available_metrics.append('Speed')

        if not available_metrics:
            return None, [], "Nessuna metrica di intensità (Watt/FC/Speed) trovata."

        # --- 4. CHECK UNITÀ DI MISURA ---
        # Se i valori medi di CHO sono < 10, sono g/min -> converti in g/h
        if clean_df['CHO'].mean() < 10.0:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        # Ordiniamo i dati per l'asse X principale per evitare grafici a "gomitolo"
        primary_sort = available_metrics[0]
        clean_df = clean_df.sort_values(by=primary_sort).reset_index(drop=True)

        return clean_df, available_metrics, None

    except Exception as e:
        return None, [], f"Errore Parsing: {str(e)}"

def find_header_row(df_temp):
    """Cerca la riga che contiene sia riferimenti ai grassi che ai carboidrati."""
    # Convertiamo tutto in stringa uppercase
    for i, row in df_temp.head(300).iterrows():
        row_str = " ".join([str(x).upper() for x in row.values])
        # Condizione: deve avere (CHO o CARBO) E (FAT o LIPID)
        if ("CHO" in row_str or "CARBO" in row_str) and ("FAT" in row_str or "LIPID" in row_str):
            # Controllo aggiuntivo: deve avere anche HR o Watt
            if any(x in row_str for x in ["HR", "FC", "WATT", "BPM"]):
                return i
    return None

#================================================================================================
# --- ZWO ---
#================================================================================================
def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
        intensity_series = [] 
        total_duration_sec = 0
        total_weighted_if = 0
        for steady_state in root.findall('.//SteadyState'):
            try:
                dur = int(steady_state.get('Duration'))
                pwr = float(steady_state.get('Power'))
                for _ in range(math.ceil(dur / 60)): intensity_series.append(pwr)
                total_duration_sec += dur
                total_weighted_if += pwr * (dur / 60) 
            except: continue
        total_min = math.ceil(total_duration_sec / 60)
        avg_val = 0
        if total_min > 0:
            avg_if = total_weighted_if / total_min
            if sport_type == SportType.CYCLING: avg_val = avg_if * ftp_watts
            elif sport_type == SportType.RUNNING: avg_val = avg_if * thr_hr
            else: avg_val = avg_if * 180 
            return intensity_series, total_min, avg_val, avg_val
        return [], 0, 0, 0
    except: return [], 0, 0, 0

# --- ZONE ---
def calculate_zones_cycling(ftp):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(ftp*p)} W"} for i, p in enumerate([0.55, 0.75, 0.90, 1.05, 1.20])]
def calculate_zones_running_hr(thr):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(thr*p)} bpm"} for i, p in enumerate([0.85, 0.89, 0.94, 0.99, 1.02])]














