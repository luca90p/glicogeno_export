import math
import pandas as pd
import numpy as np


def parse_metabolic_report(uploaded_file):
    filename = uploaded_file.name.lower()
    df = None

    try:
        uploaded_file.seek(0)

        # --- 1. LETTURA FILE ---
        if filename.endswith(('.xls', '.xlsx')):
            try:
                df_temp = pd.read_excel(uploaded_file, header=None)
                header_idx = find_header_row_index(df_temp)
                if header_idx is not None:
                    uploaded_file.seek(0)
                    df = pd.read_excel(uploaded_file, header=header_idx)
            except Exception as e:
                return None, [], f"Errore Excel: {e}"

        else:  # CSV/TXT
            encodings = ['latin-1', 'utf-8', 'cp1252']
            content = None
            used_enc = None
            for enc in encodings:
                try:
                    uploaded_file.seek(0)
                    content = uploaded_file.read().decode(enc)
                    used_enc = enc
                    break
                except:
                    continue

            if content is None:
                return None, [], "Encoding fallito."

            all_lines = content.splitlines()
            header_idx = -1
            sep = ','
            for i, line in enumerate(all_lines[:600]):
                line_up = line.upper()
                if ('CHO' in line_up or 'CARB' in line_up) and ('FAT' in line_up or 'LIPID' in line_up):
                    header_idx = i
                    if line.count(';') > line.count(','):
                        sep = ';'
                    elif line.count('\t') > line.count(','):
                        sep = '\t'
                    break

            if header_idx != -1:
                uploaded_file.seek(0)
                try:
                    df = pd.read_csv(uploaded_file, sep=sep, skiprows=header_idx, encoding=used_enc, engine='python')
                except:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, sep=sep, header=None, encoding=used_enc, engine='python')
                    df = df.iloc[header_idx + 1:].reset_index(drop=True)
                    df.columns = all_lines[header_idx].split(sep)
            else:
                return None, [], "Header non trovato."

        # --- 2. PULIZIA BASE ---
        if df is None or df.empty:
            return None, [], "File vuoto."
        df.columns = [str(c).strip().upper() for c in df.columns]

        def get_col(candidates, block=None):
            if block is None:
                block = []
            for col in df.columns:
                if any(b in col for b in block):
                    continue
                for cand in candidates:
                    if cand == col or f" {cand}" in col or f"{cand} " in col or f"({cand})" in col:
                        return col
            return None

        c_cho = get_col(['CHO', 'CARBOHYDRATES', 'QCHO'])
        c_fat = get_col(['FAT', 'LIPIDS', 'QFAT'])

        c_hr = get_col(['FC', 'HR', 'BPM', 'HEART'], block=['/', '%'])
        c_watt = get_col(['WR', 'WATT', 'POWER', 'POW', 'LOAD'], block=['/'])
        c_spd = get_col(['V', 'SPEED', 'VELOCITY', 'KM/H'], block=['/', 'VO2'])

        def to_float(col):
            if not col:
                return None
            s = df[col].astype(str).str.replace(',', '.', regex=False)
            return pd.to_numeric(s, errors='coerce')

        clean_df = pd.DataFrame()
        clean_df['CHO'] = to_float(c_cho)
        clean_df['FAT'] = to_float(c_fat)

        metrics = []
        if c_watt:
            w = to_float(c_watt)
            if w is not None and w.max() > 10:
                clean_df['Watt'] = w
                metrics.append('Watt')
        if c_hr:
            h = to_float(c_hr)
            if h is not None and h.max() > 40:
                clean_df['HR'] = h
                metrics.append('HR')
        if c_spd:
            s = to_float(c_spd)
            if s is not None and s.max() > 2:
                clean_df['Speed'] = s
                metrics.append('Speed')

        clean_df.dropna(subset=['CHO', 'FAT'], inplace=True)
        if clean_df.empty or not metrics:
            return None, [], "Dati insufficienti."

        # g/min -> g/h
        if clean_df['CHO'].mean() < 10.0:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60

        # --- 3. SMOOTHING (Pulizia Rumore) ---
        smoothed_df = apply_smoothing(clean_df, metrics)

        # --- 4. RESAMPLING UNITARIO (La tua richiesta) ---
        # Interpoliamo per avere 1 riga per ogni Watt/Bpm
        primary_metric = metrics[0]  # Usa la prima disponibile (es. Watt o HR)
        final_df = resample_to_unit_intervals(smoothed_df, primary_metric)

        # Ricalcoliamo le metriche disponibili nel df finale
        final_metrics = [c for c in metrics if c in final_df.columns]

        return final_df, final_metrics, None

    except Exception as e:
        return None, [], f"Errore Parsing: {str(e)}"


# =====================================================================
# LOGICA DI RESAMPLING (Cruciale per "Niente Salti")
# =====================================================================

def resample_to_unit_intervals(df, x_col):
    """
    Crea una Lookup Table densa interpolando i dati.
    - Watt/HR: Step 1 (es. 100, 101, 102...)
    - Speed: Step 0.1 (es. 10.0, 10.1, 10.2...)
    """
    if x_col not in df.columns:
        return df

    # 1. Definisci il range
    min_x = math.ceil(df[x_col].min())
    max_x = math.floor(df[x_col].max())

    # Se il range è troppo piccolo o nullo, ritorna l'originale
    if max_x <= min_x:
        return df

    # 2. Definisci lo step
    step = 0.1 if x_col == 'Speed' else 1.0

    # Crea il nuovo asse X denso
    # np.arange include min, esclude max -> aggiungiamo step per includere max
    new_x = np.arange(min_x, max_x + step, step)

    # 3. Interpola tutte le colonne numeriche su questo nuovo asse
    new_data = {x_col: new_x}

    # Colonne da interpolare (CHO, FAT e le altre metriche presenti)
    cols_to_interp = [c for c in df.columns if c != x_col and pd.api.types.is_numeric_dtype(df[c])]

    for col in cols_to_interp:
        # np.interp(x_nuovi, x_vecchi, y_vecchi)
        new_data[col] = np.interp(new_x, df[x_col], df[col])

    return pd.DataFrame(new_data)


# =====================================================================
# LOGICA SMOOTHING (Pulizia Rumore e Binning)
# =====================================================================

def apply_smoothing(df, metrics):
    df = df.copy()
    df = df[(df['CHO'] >= 0) & (df['FAT'] >= 0)]

    # Ordinamento (fondamentale per interpolazione)
    sort_col = metrics[0]
    df = df.sort_values(by=sort_col).reset_index(drop=True)

    # Rolling Average (Filtro Passa-Basso)
    window = 5 if len(df) < 50 else 15
    cols = ['CHO', 'FAT'] + metrics
    for c in cols:
        df[c] = df[c].rolling(window=window, min_periods=1, center=True).mean()

    # Binning (Riduce i punti ridondanti prima del resampling)
    if 'Speed' in df.columns:
        # Arrotonda ai 0.5 km/h più vicini per fare la media locale
        df['_bin'] = (df['Speed'] * 2).round() / 2
        df = df.groupby('_bin', as_index=False).mean().drop(columns=['_bin'])
    elif 'Watt' in df.columns:
        # Arrotonda ai 5 Watt
        df['_bin'] = (df['Watt'] / 5).round() * 5
        df = df.groupby('_bin', as_index=False).mean().drop(columns=['_bin'])
    else:
        # Arrotonda a 1 BPM
        df['_bin'] = df['HR'].round()
        df = df.groupby('_bin', as_index=False).mean().drop(columns=['_bin'])

    return df


def find_header_row_index(df_temp):
    for i, row in df_temp.head(600).iterrows():
        s = " ".join([str(x).upper() for x in row.values])
        if ('CHO' in s or 'CARB' in s) and ('FAT' in s or 'LIPID' in s):
            return i
    return None
