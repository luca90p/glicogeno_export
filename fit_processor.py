import fitparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import io

def process_fit_data(fit_file_object):
    """
    Legge un oggetto file .FIT (o percorso), normalizza i tempi,
    rimuove le pause e restituisce un DataFrame Pandas pulito.
    """
    print("Avvio parsing FIT...")
    
    # 1. Parsing del file FIT
    # Streamlit passa un oggetto BytesIO, fitparse lo accetta direttamente
    try:
        fitfile = fitparse.FitFile(fit_file_object)
    except Exception as e:
        return None, f"Errore lettura file: {e}"

    data_list = []

    # Estrazione messaggi 'record'
    for record in fitfile.get_messages("record"):
        record_data = {}
        for record_field in record:
            record_data[record_field.name] = record_field.value
        
        if 'timestamp' in record_data:
            data_list.append(record_data)

    if not data_list:
        return None, "Nessun dato di registrazione trovato nel file."

    # 2. Creazione DataFrame e Indicizzazione Temporale
    df = pd.DataFrame(data_list)
    df = df.set_index('timestamp').sort_index()
    
    # 3. Normalizzazione a 1 secondo (Smart Recording fix)
    # Crea una griglia completa secondo per secondo
    full_time_index = pd.date_range(start=df.index.min(), end=df.index.max(), freq='1s')
    df = df.reindex(full_time_index).ffill().fillna(0)

    # 4. Standardizzazione Colonne
    # Cerchiamo di mappare i nomi diversi usati dai vari device
    # Mappa: Nome Standard -> [Lista possibili nomi nel FIT]
    column_map = {
        'power': ['power', 'accumulated_power'], # A volte power è cumulativo, ma nel record di solito è istantaneo
        'speed': ['enhanced_speed', 'speed'],
        'altitude': ['enhanced_altitude', 'altitude'],
        'heart_rate': ['heart_rate'],
        'cadence': ['cadence']
    }

    # Rinomina le colonne trovate per avere nomi standard
    final_cols = {}
    for std_name, alternatives in column_map.items():
        for alt in alternatives:
            if alt in df.columns:
                final_cols[alt] = std_name
                break # Trovato il primo valido, stop
    
    df = df.rename(columns=final_cols)
    
    # Calcoli aggiuntivi
    if 'speed' in df.columns:
        # Se il max è basso (<100), è in m/s. Convertiamo in km/h
        if df['speed'].max() < 80: 
            df['speed_kmh'] = df['speed'] * 3.6
        else:
            df['speed_kmh'] = df['speed']
    else:
        df['speed_kmh'] = 0

    # 5. Algoritmo Pulizia Pause e Artefatti
    # Logica: Se velocità < 1.5kmh OPPURE se la velocità è identica per >15s (stallo GPS) -> PAUSA
    
    # Rileva blocchi di valori identici (stallo sensore)
    df['block_id'] = df['speed_kmh'].ne(df['speed_kmh'].shift()).cumsum()
    df['block_len'] = df.groupby('block_id')['speed_kmh'].transform('count')
    
    # Maschera: Pausa se fermo o se dato "congelato" per più di 15 secondi
    is_pause = (df['speed_kmh'] < 1.5) | ((df['block_len'] > 15) & (df['speed_kmh'] > 0))
    
    # Filtra
    df_clean = df[~is_pause].copy()
    
    # Crea asse "Tempo in Movimento" (in minuti) per i grafici
    df_clean['moving_time_min'] = np.arange(len(df_clean)) / 60.0
    
    return df_clean, None


def create_plot(df):
    """
    Prende il DataFrame pulito e restituisce una Figure di Matplotlib
    pronta per essere visualizzata su Streamlit.
    """
    # Setup stile scuro per Streamlit (opzionale)
    plt.style.use('dark_background') 
    
    fig, axes = plt.subplots(4, 1, figsize=(10, 12), sharex=True)
    
    # Colori (Palette moderna)
    c_pwr = '#FF4B4B' # Rosso Streamlit
    c_hr = '#A020F0'  # Viola
    c_cad = '#00FF00' # Verde Lime
    c_spd = '#00BFFF' # Deep Sky Blue

    # 1. POTENZA
    if 'power' in df.columns:
        axes[0].plot(df['moving_time_min'], df['power'], color=c_pwr, lw=0.8)
        axes[0].fill_between(df['moving_time_min'], df['power'], color=c_pwr, alpha=0.3)
        axes[0].set_ylabel('Watt', fontweight='bold', color=c_pwr)
        # Media mobile 30s per pulizia visiva
        axes[0].plot(df['moving_time_min'], df['power'].rolling(30).mean(), color='white', lw=1.5, alpha=0.8, label='Avg 30s')
        axes[0].legend(loc='upper right', fontsize='small')
    
    # 2. FREQUENZA CARDIACA
    if 'heart_rate' in df.columns:
        axes[1].plot(df['moving_time_min'], df['heart_rate'], color=c_hr, lw=1)
        axes[1].set_ylabel('BPM', fontweight='bold', color=c_hr)
        axes[1].grid(True, linestyle=':', alpha=0.3)

    # 3. CADENZA
    if 'cadence' in df.columns:
        # Rimuoviamo gli zeri per il grafico
        cad_view = df['cadence'].replace(0, np.nan)
        axes[2].scatter(df['moving_time_min'], cad_view, color=c_cad, s=1, alpha=0.6)
        axes[2].set_ylabel('RPM', fontweight='bold', color=c_cad)
        axes[2].set_ylim(30, 130)

    # 4. VELOCITÀ & ALTITUDINE
    ax4 = axes[3]
    if 'speed_kmh' in df.columns:
        ax4.plot(df['moving_time_min'], df['speed_kmh'], color=c_spd, lw=1)
        ax4.fill_between(df['moving_time_min'], df['speed_kmh'], color=c_spd, alpha=0.2)
        ax4.set_ylabel('Km/h', fontweight='bold', color=c_spd)
    
    # Asse secondario per Altitudine
    if 'altitude' in df.columns:
        ax_alt = ax4.twinx()
        ax_alt.plot(df['moving_time_min'], df['altitude'], color='gray', alpha=0.5, lw=1)
        ax_alt.fill_between(df['moving_time_min'], df['altitude'], color='gray', alpha=0.1)
        ax_alt.set_ylabel('Metri', color='white')
        ax_alt.grid(False)

    ax4.set_xlabel('Tempo in Movimento (minuti)')
    
    # Titolo generale nascosto (lo mettiamo in Streamlit come testo)
    plt.tight_layout()
    
    return fig
