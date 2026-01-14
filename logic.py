import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState, GlycogenState, IntakeMode, SportType

# --- 1. FUNZIONI HELPER ---

def get_concentration_from_vo2max(vo2_max):
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    return max(12.0, min(26.0, conc))

def calculate_rer_polynomial(intensity_factor):
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 141.538462237 * (if_val**5) - 565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 691.679487060 * (if_val**2) + 265.460857558 * if_val - 39.525121144)
    return max(0.70, min(1.15, rer))

def calculate_depletion_factor(steps, activity_min, s_fatigue):
    steps_base = 10000 
    steps_factor = (steps - steps_base) / 5000 * 0.1 * 0.4
    activity_base = 120 
    if activity_min < 60: 
        activity_factor = (1 - (activity_min / 60)) * 0.05 * 0.6
    else:
        activity_factor = (activity_min - activity_base) / 60 * -0.1 * 0.6
    depletion_impact = steps_factor + activity_factor
    return max(0.6, min(1.0, 1.0 + depletion_impact))

def calculate_filling_factor_from_diet(weight_kg, cho_d1, cho_d2, s_fatigue, s_sleep, steps_m1, min_act_m1, steps_m2, min_act_m2):
    CHO_BASE_GK = 5.0
    CHO_MAX_GK = 10.0
    CHO_MIN_GK = 2.5
    cho_d1_gk = max(cho_d1, 1.0) / weight_kg
    cho_d2_gk = max(cho_d2, 1.0) / weight_kg
    avg_cho_gk = (cho_d1_gk * 0.7) + (cho_d2_gk * 0.3)
    
    if avg_cho_gk >= CHO_MAX_GK: diet_factor = 1.25
    elif avg_cho_gk >= CHO_BASE_GK: diet_factor = 1.0 + (avg_cho_gk - CHO_BASE_GK) * (0.25 / (CHO_MAX_GK - CHO_BASE_GK))
    elif avg_cho_gk > CHO_MIN_GK: diet_factor = 0.5 + (avg_cho_gk - CHO_MIN_GK) * (0.5 / (CHO_BASE_GK - CHO_MIN_GK))
    else: diet_factor = 0.5
    
    diet_factor = min(1.25, max(0.5, diet_factor))
    depletion = calculate_depletion_factor(steps_m1, min_act_m1, s_fatigue)
    final_filling = diet_factor * depletion * s_sleep.factor
    return final_filling, diet_factor, avg_cho_gk, cho_d1_gk, cho_d2_gk

def calculate_tank(subject: Subject):
    if subject.muscle_mass_kg is not None and subject.muscle_mass_kg > 0:
        total_muscle = subject.muscle_mass_kg
        muscle_source_note = "Massa Muscolare Misurata"
    else:
        lbm = subject.lean_body_mass
        total_muscle = lbm * subject.muscle_fraction
        muscle_source_note = "Massa Muscolare Stimata"

    active_muscle = total_muscle * subject.sport.val
    creatine_multiplier = 1.10 if subject.uses_creatine else 1.0
    base_muscle_glycogen = active_muscle * subject.glycogen_conc_g_kg
    max_total_capacity = (base_muscle_glycogen * 1.25 * creatine_multiplier) + 100.0
    final_filling_factor = subject.filling_factor * subject.menstrual_phase.factor
    current_muscle_glycogen = base_muscle_glycogen * creatine_multiplier * final_filling_factor
    max_physiological_limit = active_muscle * 35.0
    if current_muscle_glycogen > max_physiological_limit: current_muscle_glycogen = max_physiological_limit
    
    liver_fill_factor = 1.0
    if subject.filling_factor <= 0.6: liver_fill_factor = 0.6
    if subject.glucose_mg_dl is not None:
        if subject.glucose_mg_dl < 70: liver_fill_factor = 0.2
        elif subject.glucose_mg_dl < 85: liver_fill_factor = min(liver_fill_factor, 0.5)
    
    current_liver_glycogen = subject.liver_glycogen_g * liver_fill_factor
    total_actual_glycogen = current_muscle_glycogen + current_liver_glycogen
    
    return {
        "active_muscle_kg": active_muscle,
        "max_capacity_g": max_total_capacity,         
        "actual_available_g": total_actual_glycogen,   
        "muscle_glycogen_g": current_muscle_glycogen,
        "liver_glycogen_g": current_liver_glycogen,
        "concentration_used": subject.glycogen_conc_g_kg,
        "fill_pct": (total_actual_glycogen / max_total_capacity) * 100 if max_total_capacity > 0 else 0,
        "muscle_source_note": muscle_source_note
    }

def interpolate_consumption(current_val, curve_data):
    if isinstance(curve_data, pd.DataFrame):
        cho = np.interp(current_val, curve_data['Intensity'], curve_data['CHO'])
        fat = np.interp(current_val, curve_data['Intensity'], curve_data['FAT'])
        return cho, fat
    elif isinstance(curve_data, dict):
        p1, p2, p3 = curve_data['z2'], curve_data['z3'], curve_data['z4']
        if current_val <= p1['hr']: return p1['cho'], p1['fat'] 
        if current_val <= p2['hr']:
            ratio = (current_val - p1['hr']) / (p2['hr'] - p1['hr'])
            return p1['cho'] + ratio*(p2['cho']-p1['cho']), p1['fat'] + ratio*(p2['fat']-p1['fat'])
        elif current_val <= p3['hr']:
            ratio = (current_val - p2['hr']) / (p3['hr'] - p2['hr'])
            return p2['cho'] + ratio*(p3['cho']-p2['cho']), p2['fat'] + ratio*(p3['fat']-p2['fat'])
        else:
            extra = current_val - p3['hr']
            return p3['cho'] + (extra * 4.0), max(0.0, p3['fat'] - extra * 0.5)
    return 0, 0

def estimate_max_exogenous_oxidation(height_cm, weight_kg, ftp_watts, mix_type: ChoMixType):
    base_rate = 0.8 
    if height_cm > 170: base_rate += (height_cm - 170) * 0.015
    if ftp_watts > 200: base_rate += (ftp_watts - 200) * 0.0015
    estimated_rate_gh = base_rate * 60 * mix_type.ox_factor
    final_rate_g_min = min(estimated_rate_gh / 60, mix_type.max_rate_gh / 60)
    return final_rate_g_min

# --- 2. MOTORE TAPERING (LOGICA ORARIA AVANZATA) ---

def calculate_hourly_tapering(subject, days_data, start_state: GlycogenState = GlycogenState.NORMAL):
    
    # 1. Inizializzazione Serbatoi
    tank = calculate_tank(subject)
    MAX_MUSCLE = tank['max_capacity_g'] - 100 
    MAX_LIVER = 100.0
    
    # Start level
    start_factor = start_state.factor
    curr_muscle = min(MAX_MUSCLE * start_factor, MAX_MUSCLE)
    curr_liver = min(MAX_LIVER * start_factor, MAX_LIVER)
    
    hourly_log = []
    
    # Costanti Fisiologiche Orarie
    LIVER_DRAIN_H = 4.0 # Consumo cervello/organi (g/h)
    NEAT_DRAIN_H = (1.0 * subject.weight_kg) / 16.0 # NEAT spalmato sulle 16h di veglia (g/h)
    
    # Ciclo sui Giorni
    for day_idx, day in enumerate(days_data):
        date_label = day['date_obj'].strftime("%d/%m")
        
        # Parsing Orari
        sleep_start = day['sleep_start'].hour + (day['sleep_start'].minute/60)
        sleep_end = day['sleep_end'].hour + (day['sleep_end'].minute/60)
        # Gestione notte (es. 23:00 -> 07:00). Se sleep_start > sleep_end, scavalca la mezzanotte
        
        work_start = day['workout_start'].hour + (day['workout_start'].minute/60)
        work_dur_h = day['duration'] / 60.0
        work_end = work_start + work_dur_h
        
        total_cho_input = day['cho_in']
        
        # Calcolo Ore di Veglia (Feeding Window) per distribuire il cibo
        # Semplificazione: Assumiamo che si mangi uniformemente quando si è svegli e non ci si allena
        waking_hours = 0
        for h in range(24):
            is_sleeping = False
            if sleep_start > sleep_end: # Scavalca notte (es 23-07)
                if h >= sleep_start or h < sleep_end: is_sleeping = True
            else:
                if sleep_start <= h < sleep_end: is_sleeping = True
            
            is_working = (work_start <= h < work_end)
            if not is_sleeping and not is_working:
                waking_hours += 1
        
        cho_rate_h = total_cho_input / waking_hours if waking_hours > 0 else 0
        
        # Ciclo sulle 24 ore del giorno
        for h in range(24):
            status = "REST"
            is_sleeping = False
            
            # Check Sonno
            if sleep_start > sleep_end:
                if h >= sleep_start or h < sleep_end: is_sleeping = True
            else:
                if sleep_start <= h < sleep_end: is_sleeping = True
            
            if is_sleeping: status = "SLEEP"
            
            # Check Allenamento (Prioritario sul sonno se configurato male)
            if work_start <= h < work_end:
                status = "WORK"
            
            # --- BILANCIO ORARIO ---
            hourly_in = 0
            hourly_out_liver = LIVER_DRAIN_H # Sempre attivo (cervello)
            hourly_out_muscle = 0
            
            if status == "SLEEP":
                hourly_in = 0 # Non mangi mentre dormi
                # Sintesi facilitata durante il sonno (se c'è surplus precedente, ma qui è real time)
            
            elif status == "WORK":
                hourly_in = 0 # Assumiamo integrazione separata o nulla nel tapering
                # Calcolo consumo lavoro
                intensity = day.get('calculated_if', 0)
                # Stima Kcal/h lavoro
                kcal_work = (day.get('val', 0) * 60) / 4.184 / 0.22 if day.get('type') == 'Ciclismo' else 600 * intensity
                # CHO usage durante lavoro (dipende da intensità, usiamo stima RER macro)
                # IF 0.6 -> 20% CHO, IF 0.8 -> 60% CHO, IF 0.9 -> 80% CHO
                cho_pct = max(0, (intensity - 0.5) * 2.5) 
                cho_pct = min(1.0, cho_pct)
                g_cho_work = (kcal_work * cho_pct) / 4.1
                
                # Split consumo lavoro (Muscolo vs Fegato)
                # Più è intenso, più usa muscolo
                liver_share = 0.15 # Il fegato contribuisce sempre un po' sotto sforzo
                hourly_out_muscle = g_cho_work * (1 - liver_share)
                hourly_out_liver += g_cho_work * liver_share
                
            elif status == "REST":
                hourly_in = cho_rate_h
                hourly_out_muscle = NEAT_DRAIN_H # Piccolo consumo per muoversi
            
            # --- CALCOLO NETTO ---
            net_flow = hourly_in - (hourly_out_liver + hourly_out_muscle)
            
            # Applicazione ai serbatoi (Ripartizione)
            if net_flow > 0:
                # REFILLING (Priorità Muscolo 70/30)
                # Se muscolo pieno, tutto a fegato (e viceversa)
                
                # Efficienza assorbimento (Sonno penalizza se fosse attivo, ma qui siamo svegli)
                # Usiamo il fattore qualità del sonno del giorno PRECEDENTE/CORRENTE come efficienza metabolica generale
                efficiency = day['sleep_factor'] 
                real_storage = net_flow * efficiency
                
                to_muscle = real_storage * 0.7
                to_liver = real_storage * 0.3
                
                # Overflow Logic
                if curr_muscle + to_muscle > MAX_MUSCLE:
                    overflow = (curr_muscle + to_muscle) - MAX_MUSCLE
                    to_muscle -= overflow
                    to_liver += overflow # Il fegato prova a prenderlo (lipogenesi dopo)
                
                curr_muscle = min(MAX_MUSCLE, curr_muscle + to_muscle)
                curr_liver = min(MAX_LIVER, curr_liver + to_liver)
                
            else:
                # DRAINING
                # Se stiamo lavorando, abbiamo già diviso out_muscle e out_liver
                # Se è deficit basale, lo dividiamo 50/50 o attingiamo al fegato
                
                abs_deficit = abs(net_flow)
                
                if status == "WORK":
                    # Il consumo è già diviso in hourly_out_...
                    # Ma hourly_in potrebbe coprire parte. Semplifichiamo:
                    # Applichiamo i consumi diretti
                    # L'input copre prima il fegato (sangue), poi risparmia muscolo
                    
                    # Ricalcolo flussi separati con intake
                    # Intake supporta prima il fegato (glicemia)
                    liver_balance = (hourly_in) - hourly_out_liver
                    if liver_balance < 0:
                        curr_liver += liver_balance # Scende
                    else:
                        # Surplus epatico momentaneo protegge muscolo? No, va a scorte o ossidazione
                        curr_liver += liver_balance # Sale o pari
                        
                    curr_muscle -= hourly_out_muscle
                    
                else:
                    # Deficit a riposo/sonno (Liver drain + NEAT)
                    # Il fegato copre quasi tutto a riposo
                    curr_liver -= (abs_deficit * 0.8)
                    curr_muscle -= (abs_deficit * 0.2)

            # Clamping (Non sotto zero)
            curr_muscle = max(0, curr_muscle)
            curr_liver = max(0, curr_liver)
            
            # Costruzione Timestamp per Grafico
            # Usiamo un datetime fittizio o reale per l'asse X
            ts = pd.Timestamp(day['date_obj']) + pd.Timedelta(hours=h)
            
            hourly_log.append({
                "Timestamp": ts,
                "Giorno": date_label,
                "Ora": h,
                "Status": status,
                "Muscolare": curr_muscle,
                "Epatico": curr_liver,
                "Totale": curr_muscle + curr_liver,
                "Zona": "Sicura" if curr_liver > 20 else "Rischio"
            })

    final_tank = tank.copy()
    final_tank['muscle_glycogen_g'] = curr_muscle
    final_tank['liver_glycogen_g'] = curr_liver
    final_tank['actual_available_g'] = curr_muscle + curr_liver
    final_tank['fill_pct'] = (curr_muscle + curr_liver) / (MAX_MUSCLE + MAX_LIVER) * 100
    
    return pd.DataFrame(hourly_log), final_tank

# funzione simulazione metabolica

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        custom_max_exo_rate=None, mix_type_input=ChoMixType.GLUCOSE_ONLY, 
                        intensity_series=None, metabolic_curve=None, 
                        intake_mode=IntakeMode.DISCRETE, intake_cutoff_min=0, variability_index=1.0, 
                        use_mader=False, running_method="PHYSIOLOGICAL"):
    
    results = []
    initial_muscle_glycogen = subject_data['muscle_glycogen_g']
    current_muscle_glycogen = initial_muscle_glycogen
    current_liver_glycogen = subject_data['liver_glycogen_g']
    
    # PARAMETRI ATTIVITÀ
    avg_watts = activity_params.get('avg_watts', 200)
    np_watts = activity_params.get('np_watts', avg_watts)
    ftp_watts = activity_params.get('ftp_watts', 250)
    
    threshold_hr = activity_params.get('threshold_hr', 170)
    gross_efficiency = activity_params.get('efficiency', 22.0)
    mode = activity_params.get('mode', 'cycling')
    avg_hr = activity_params.get('avg_hr', 150)
    
    threshold_ref = ftp_watts if mode == 'cycling' else threshold_hr
    base_val = avg_watts if mode == 'cycling' else avg_hr
    
    if mode == 'cycling' and ftp_watts > 0:
        intensity_factor_reference = np_watts / ftp_watts
    elif threshold_ref > 0:
        intensity_factor_reference = base_val / threshold_ref
    else:
        intensity_factor_reference = 0.8
    
    # --- FIX RUNNING: CALCOLO KCAL BASE ---
    if mode == 'cycling':
        # Ciclismo: Fisica pura (Watt -> Kcal)
        kcal_per_min_base = (avg_watts * 60) / 4184 / (gross_efficiency / 100.0)
    else:
        # Running: Stima basata su VO2max invece che formula generica
        # Assumiamo che la Soglia (HR Threshold) sia al 90% del VO2max
        vo2_threshold_pct = 0.90
        
        # VO2 stimato (ml/kg/min) in base all'intensità cardiaca rispetto alla soglia
        vo2_estimated_relative = subject_obj.vo2_max * vo2_threshold_pct * intensity_factor_reference
        
        # VO2 assoluto (L/min)
        vo2_estimated_absolute = (vo2_estimated_relative * subject_obj.weight_kg) / 1000.0
        
        # Kcal/min (1 L O2 ~ 4.85 Kcal a RER misto/alto)
        kcal_per_min_base = vo2_estimated_absolute * 4.85
        
    is_lab_data = True if metabolic_curve is not None else False 
    
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate 
    else:
        max_exo_rate_g_min = estimate_max_exogenous_oxidation(
            subject_obj.height_cm, subject_obj.weight_kg, ftp_watts, mix_type_input
        )
    
    gut_accumulation_total = 0.0
    current_exo_oxidation_g_min = 0.0 
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    total_fat_burned_g = 0.0
    total_intake_cumulative = 0.0
    total_exo_oxidation_cumulative = 0.0
    
    units_per_hour = constant_carb_intake_g_h / cho_per_unit_g if cho_per_unit_g > 0 else 0
    intake_interval_min = round(60 / units_per_hour) if units_per_hour > 0 else duration_min + 1
    is_input_zero = constant_carb_intake_g_h == 0
    
    # Loop Temporale
    for t in range(int(duration_min) + 1):
        
        # Determine Current Intensity
        current_val = base_val
        current_if_moment = intensity_factor_reference

        if intensity_series is not None and t < len(intensity_series):
            current_val = intensity_series[t]
            current_if_moment = current_val / threshold_ref if threshold_ref > 0 else 0.8
        elif variability_index > 1.0:
             current_if_moment *= variability_index
        
        # Calcolo Domanda Energetica Istantanea
        current_kcal_demand = 0.0
        if mode == 'cycling':
            instant_power = current_val
            current_eff = gross_efficiency
            if t > 60: 
                loss = (t - 60) * 0.02
                current_eff = max(15.0, gross_efficiency - loss)
            current_kcal_demand = (instant_power * 60) / 4184 / (current_eff / 100.0)
        else: 
            # Running: Drift cardiaco (aumento costo apparente)
            drift_factor = 1.0
            if t > 60: drift_factor += (t - 60) * 0.0005 
            demand_scaling = current_if_moment / intensity_factor_reference if intensity_factor_reference > 0 else 1.0
            current_kcal_demand = kcal_per_min_base * drift_factor * demand_scaling
        
        # --- INTAKE ---
        instantaneous_input_g_min = 0.0 
        in_feeding_window = t <= (duration_min - intake_cutoff_min)
        
        is_discrete = False
        try:
             if intake_mode and intake_mode.name == 'DISCRETE': is_discrete = True
        except: pass

        if not is_input_zero and in_feeding_window:
            if is_discrete:
                if t == 0 or (t > 0 and intake_interval_min > 0 and t % intake_interval_min == 0):
                    instantaneous_input_g_min = cho_per_unit_g 
            else:
                instantaneous_input_g_min = constant_carb_intake_g_h / 60.0
        
        # Exogenous Oxidation Logic
        user_intake_rate = constant_carb_intake_g_h / 60.0 
        effective_target = min(user_intake_rate, max_exo_rate_g_min) * oxidation_efficiency_input
        if is_input_zero: effective_target = 0.0

        if t >= 0:
            if is_input_zero:
                current_exo_oxidation_g_min *= (1 - alpha) 
            else:
                current_exo_oxidation_g_min += alpha * (effective_target - current_exo_oxidation_g_min)
            
            current_exo_oxidation_g_min = max(0.0, current_exo_oxidation_g_min)
            
            gut_accumulation_total += (instantaneous_input_g_min * oxidation_efficiency_input)
            real_oxidation = min(current_exo_oxidation_g_min, gut_accumulation_total)
            current_exo_oxidation_g_min = real_oxidation
            gut_accumulation_total -= real_oxidation
            if gut_accumulation_total < 0: gut_accumulation_total = 0 
            
            total_intake_cumulative += instantaneous_input_g_min 
            total_exo_oxidation_cumulative += current_exo_oxidation_g_min
        
        # --- CONSUMO SUBSTRATI ---
        cho_ratio = 1.0
        rer = 0.85
        total_cho_demand = 0.0
        g_fat = 0.0

        if is_lab_data:
            cho_rate_gh, fat_rate_gh = interpolate_consumption(current_val, metabolic_curve)
            if t > 60:
                drift = 1.0 + ((t - 60) * 0.0006)
                cho_rate_gh *= drift
                fat_rate_gh *= (1.0 - ((t - 60) * 0.0003))
            total_cho_demand = cho_rate_gh / 60.0
            g_fat = fat_rate_gh / 60.0
            rer = 0.85 
        else:
            # --- INTEGRAZIONE MADER (AVANZATA) ---
            if use_mader:
                mader_watts_input = current_val # Default Ciclismo
                
                # Logica Specifica Corsa
                if mode == 'running':
                    # A. STRADA FISIOLOGICA (HR -> Kcal -> Watt Equivalenti)
                    if running_method == "PHYSIOLOGICAL":
                         # Invertiamo la formula delle Kcal per trovare i Watt equivalenti allo sforzo cardiaco
                         # Kcal/min = (Watts * 0.01433) / 0.21 (Efficienza Corsa)
                         mader_watts_input = (current_kcal_demand * 0.21) / 0.01433
                    
                    # B. STRADA MECCANICA (Speed -> Watt)
                    else:
                        if current_val > 50: # Input già in Watt (Stryd)
                             mader_watts_input = current_val
                        else:
                             # Input in km/h -> Watt
                             speed_ms = current_val / 3.6
                             # Formula approx: Peso * Speed(m/s) * Costo(J/kg/m ~1.04)
                             mader_watts_input = speed_ms * subject_obj.weight_kg * 1.04

                # Calcolo Mader Puro con Watt (reali o stimati)
                mader_cho_g_min = calculate_mader_consumption(mader_watts_input, subject_obj)
                total_cho_demand = mader_cho_g_min
                
                # Calcola grassi per differenza calorica
                # Usiamo le Kcal calcolate dal modello HR (current_kcal_demand) per coerenza col dispendio totale
                kcal_cho = total_cho_demand * 4.0
                kcal_fat = max(0, current_kcal_demand - kcal_cho)
                g_fat = kcal_fat / 9.0
                
                # Stima parametri per output
                if current_kcal_demand > 0:
                    cho_ratio = kcal_cho / current_kcal_demand
                rer = 0.7 + (0.3 * cho_ratio)
            else:
                # LOGICA STANDARD (CROSSOVER)
                standard_crossover = 75.0 
                crossover_val = crossover_pct if crossover_pct else standard_crossover
                if_shift = (standard_crossover - crossover_val) / 100.0
                effective_if_for_rer = max(0.3, current_if_moment + if_shift)
                
                rer = calculate_rer_polynomial(effective_if_for_rer)
                base_cho_ratio = (rer - 0.70) * 3.45
                base_cho_ratio = max(0.0, min(1.0, base_cho_ratio))
                
                current_cho_ratio = base_cho_ratio
                if current_if_moment < 0.85 and t > 60:
                    hours_past = (t - 60) / 60.0
                    metabolic_shift = 0.05 * (hours_past ** 1.2) 
                    current_cho_ratio = max(0.05, base_cho_ratio - metabolic_shift)
                
                cho_ratio = current_cho_ratio
                kcal_cho_demand = current_kcal_demand * cho_ratio
                total_cho_demand = kcal_cho_demand / 4.1
                g_fat = (current_kcal_demand * (1.0-cho_ratio) / 9.0) if current_kcal_demand > 0 else 0
        
        total_cho_g_min = total_cho_demand
        
        # --- RIPARTIZIONE GLICOGENO ---
        muscle_fill_state = current_muscle_glycogen / initial_muscle_glycogen if initial_muscle_glycogen > 0 else 0
        muscle_contribution_factor = math.pow(muscle_fill_state, 0.6) 
        muscle_usage_g_min = total_cho_g_min * muscle_contribution_factor
        if current_muscle_glycogen <= 0: muscle_usage_g_min = 0
        
        blood_glucose_demand_g_min = total_cho_g_min - muscle_usage_g_min
        from_exogenous = min(blood_glucose_demand_g_min, current_exo_oxidation_g_min)
        remaining_blood_demand = blood_glucose_demand_g_min - from_exogenous
        max_liver_output = 1.2 
        from_liver = min(remaining_blood_demand, max_liver_output)
        if current_liver_glycogen <= 0: from_liver = 0
        
        # Update Riserve
        if t > 0:
            current_muscle_glycogen -= muscle_usage_g_min
            current_liver_glycogen -= from_liver
            
            if current_muscle_glycogen < 0: current_muscle_glycogen = 0
            if current_liver_glycogen < 0: current_liver_glycogen = 0
            
            total_fat_burned_g += g_fat
            total_muscle_used += muscle_usage_g_min
            total_liver_used += from_liver
            total_exo_used += from_exogenous
        
        status_label = "Ottimale"
        if current_liver_glycogen < 20: status_label = "CRITICO (Ipoglicemia)"
        elif current_muscle_glycogen < 100: status_label = "Warning (Gambe Vuote)"
        
        total_g_min = max(1.0, muscle_usage_g_min + from_liver + from_exogenous + g_fat)
        
        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": muscle_usage_g_min * 60, 
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": from_exogenous * 60, 
            "Ossidazione Lipidica (g)": g_fat * 60,
            "Pct_Muscle": f"{(muscle_usage_g_min / total_g_min * 100):.1f}%",
            "Pct_Liver": f"{(from_liver / total_g_min * 100):.1f}%",
            "Pct_Exo": f"{(from_exogenous / total_g_min * 100):.1f}%",
            "Pct_Fat": f"{(g_fat / total_g_min * 100):.1f}%",
            "Residuo Muscolare": current_muscle_glycogen,
            "Residuo Epatico": current_liver_glycogen,
            "Residuo Totale": current_muscle_glycogen + current_liver_glycogen,
            "Target Intake (g/h)": constant_carb_intake_g_h,
            "Gut Load": gut_accumulation_total,
            "Stato": status_label,
            "CHO %": cho_ratio * 100,
            "Intake Cumulativo (g)": total_intake_cumulative,
            "Ossidazione Cumulativa (g)": total_exo_oxidation_cumulative,
            "Intensity Factor (IF)": current_if_moment
        })
    
    # Statistiche Finali
    total_kcal_final = (avg_watts * duration_min * 60) / 4184 / (gross_efficiency/100)
    final_total_glycogen = current_muscle_glycogen + current_liver_glycogen
    
    stats = {
        "final_glycogen": final_total_glycogen,
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned_g,
        "kcal_total_h": total_kcal_final,
        "intensity_factor": intensity_factor_reference,
        "avg_rer": rer,
        "cho_pct": cho_ratio * 100
    }
    return pd.DataFrame(results), stats

# --- 4. CALCOLO REVERSE STRATEGY ---

# --- 4. CALCOLO REVERSE STRATEGY (AGGIORNATA) ---

def calculate_minimum_strategy(tank, duration, subj, params, curve_data, mix_type, intake_mode, intake_cutoff_min=0, variability_index=1.0, intensity_series=None, use_mader=False, running_method="PHYSIOLOGICAL"):
    """
    Calcola la strategia nutrizionale minima necessaria.
    Itera simulazioni aumentando l'intake finché i serbatoi non rimangono sopra la soglia di sicurezza.
    """
    optimal = None
    
    # Definiamo i limiti di sicurezza (Stop prima di svuotare tutto)
    MIN_LIVER_SAFE = 5.0   # Grammi minimi fegato
    MIN_MUSCLE_SAFE = 20.0 # Grammi minimi muscolo
    
    # Iteriamo l'intake da 0 a 120 g/h con step di 5g
    for intake in range(0, 125, 5):
        
        # Eseguiamo la simulazione passando TUTTI i parametri, incluso running_method
        df, stats = simulate_metabolism(
            subject_data=tank, 
            duration_min=duration, 
            constant_carb_intake_g_h=intake, 
            cho_per_unit_g=30, # Valore dummy per il calcolo continuo
            crossover_pct=75,  # Valore dummy se usiamo Mader
            tau_absorption=20, 
            subject_obj=subj, 
            activity_params=params, 
            mix_type_input=mix_type, 
            metabolic_curve=curve_data,
            intake_mode=intake_mode, 
            intake_cutoff_min=intake_cutoff_min,
            variability_index=variability_index,
            intensity_series=intensity_series,
            use_mader=use_mader,          # <--- Fondamentale
            running_method=running_method # <--- NUOVO: Passa la modalità Corsa
        )
        
        # Verifichiamo i minimi raggiunti durante la gara
        min_liver = df['Residuo Epatico'].min()
        min_muscle = df['Residuo Muscolare'].min()
        
        # Criterio di successo: Non andiamo mai sotto i minimi di sicurezza
        if min_liver > MIN_LIVER_SAFE and min_muscle > MIN_MUSCLE_SAFE:
            optimal = intake
            break
            
    return optimal
# ==============================================================================
# MODULO MORTON / SKIBA (W' BALANCE)
# ==============================================================================

def calculate_w_prime_balance(intensity_series, cp_watts, w_prime_j, sampling_interval_sec=60):
    """
    Calcola il bilancio di W' (W_prime) utilizzando il modello di Skiba (2012)
    per il recupero esponenziale variabile.
    
    Args:
        intensity_series: Lista di valori di potenza (Watt).
        cp_watts: Critical Power dell'atleta.
        w_prime_j: Capacità di lavoro anaerobico (Joule).
        sampling_interval_sec: Durata di ogni step (default 60s per la logica dell'app).
    
    Returns:
        Lista con i valori residui di W' (Joule) per ogni istante.
    """
    balance = []
    current_w = w_prime_j
    
    for p in intensity_series:
        if p > cp_watts:
            # --- DEPLEZIONE (Lineare) ---
            # W' si consuma linearmente in base a quanto sei sopra la CP
            usage = (p - cp_watts) * sampling_interval_sec
            current_w -= usage
        else:
            # --- RECUPERO (Esponenziale Skiba) ---
            # La velocità di recupero dipende da quanto vai PIANO rispetto alla CP.
            # Più sei sotto soglia, più veloce ricarichi.
            d_cp = cp_watts - p
            if d_cp < 0: d_cp = 0 # Safety check
            
            # Costante di tempo Tau dinamica (Skiba 2012)
            # Tau = 546 * e^(-0.01 * D_CP) + 316
            tau = 546 * math.exp(-0.01 * d_cp) + 316
            
            # Formula di ricostituzione asintotica verso W'_max
            # W_new = W_max - (W_max - W_prev) * e^(-dt/tau)
            current_w = w_prime_j - (w_prime_j - current_w) * math.exp(-sampling_interval_sec / tau)

        # Clamp ai limiti fisici (0 = Esaurimento, W'_max = Pieno)
        if current_w > w_prime_j: current_w = w_prime_j
        if current_w < 0: current_w = 0 
        
        balance.append(current_w)
        
    return balance

# --- MOTORE FISIOLOGICO MADER ---

def calculate_mader_consumption(watts, subject: Subject, custom_efficiency=None):
    """
    Calcola il consumo di CHO (g/min) basato su VO2max e VLaMax.
    Supporta efficienza personalizzata.
    """
    # 0. Costanti di Calibrazione
    VLA_SCALE = 0.07
    K_COMB = 0.0225
    
    # 1. Efficienza Meccanica (Dinamica)
    if custom_efficiency is not None:
        eff = custom_efficiency / 100.0 # Convertiamo 22.0 in 0.22
    else:
        # Fallback ai default se non specificato
        eff = 0.23 if subject.sport == SportType.CYCLING else 0.21
    
    # 2. Domanda Energetica (VO2 Demand)
    # Più bassa è l'efficienza, più alto è il VO2 richiesto per gli stessi Watt
    kcal_min = (watts * 0.01433) / eff
    vo2_demand_ml = (kcal_min / 4.85) * 1000
    
    # 2. Domanda Energetica
    kcal_min = (watts * 0.01433) / eff
    vo2_demand_ml = (kcal_min / 4.85) * 1000
    vo2_max_abs = subject.vo2_max * subject.weight_kg
    
    if vo2_max_abs == 0: return 0
    intensity = vo2_demand_ml / vo2_max_abs
    
    # 3. Produzione Lattato (Systemic Appearance)
    # VLaMax * 60 * Intensity^3 * Scala
    raw_prod = (subject.vlamax * 60) * (max(0, intensity) ** 3)
    vla_prod = raw_prod * VLA_SCALE
    
    # 4. Combustione Lattato (Clearance)
    # La capacità di smaltimento dipende dal VO2 effettivo (mitocondri attivi)
    vo2_uptake = min(vo2_demand_ml, vo2_max_abs)
    vla_comb = K_COMB * (vo2_uptake / subject.weight_kg)
    
    net_balance = vla_prod - vla_comb
    
    # 5. Consumo Aerobico (RER Dinamico)
    # Base RER più conservativo per evitare sovrastima CHO a bassa intensità
    base_rer = 0.70 + (0.18 * intensity) 
    
    # Lactate Push: Il lattato spinge il metabolismo verso i CHO, ma ora è scalato
    lactate_push = min(0.25, vla_prod * 0.15)
    
    final_rer = min(1.0, max(0.7, base_rer + lactate_push))
    
    cho_pct = (final_rer - 0.7) / 0.3
    cho_aerobic = (kcal_min * cho_pct) / 4.0
    
    # 6. Consumo Anaerobico (Solo Accumulo Netto)
    # Aggiungiamo solo i carboidrati "persi" come lattato non ossidato (sopra soglia)
    # Se net_balance < 0 (sotto soglia), il costo è zero (tutto ossidato e conteggiato in RER)
    vol_dist = subject.weight_kg * 0.40
    cho_anaerobic = max(0, net_balance) * vol_dist * 0.09
    
    return cho_aerobic + cho_anaerobic

def simulate_mader_curve(subject: Subject):
    """
    Genera i dati per il Tab Laboratorio.
    Supporta CICLISMO e CORSA con parametri fisiologici differenziati.
    """
    watts_range = np.arange(0, 600, 10)
    results = []
    
    # 1. SETUP PARAMETRI SPORT-SPECIFICI
    if subject.sport == SportType.RUNNING:
        # CORSA
        # Efficienza minore (più dispendioso a parità di Watt meccanici)
        # Nota: Se usi Stryd, l'efficienza metabolica è calibrata diversamente, ma usiamo 0.21 come standard
        eff = 0.21 
        # Massa muscolare attiva maggiore (diluizione lattato su più volume)
        active_mass_pct = 0.45 
        # Costante di smaltimento leggermente aumentata (miglior pompa muscolare/circolazione total body)
        K_COMB = 0.024 
    else:
        # CICLISMO
        eff = 0.23
        active_mass_pct = 0.40
        K_COMB = 0.0225

    VLA_SCALE = 0.07 # Costante di scala produzione (fissa)
    
    for w in watts_range:
        # A. Domanda Energetica
        kcal_min = (w * 0.01433) / eff
        vo2_demand_ml = (kcal_min / 4.85) * 1000
        vo2_max_abs = subject.vo2_max * subject.weight_kg
        
        intensity = 0
        if vo2_max_abs > 0:
            intensity = vo2_demand_ml / vo2_max_abs
            
        # B. Lattato: Produzione vs Smaltimento
        raw_prod = (subject.vlamax * 60) * (max(0, intensity) ** 3)
        vla_prod = raw_prod * VLA_SCALE
        
        vo2_uptake = min(vo2_demand_ml, vo2_max_abs)
        vla_comb = K_COMB * (vo2_uptake / subject.weight_kg)
        
        net_balance = vla_prod - vla_comb
        
        # C. Dati Ossigeno
        vo2_demand_l = vo2_demand_ml / 1000.0
        vo2_uptake_l = vo2_uptake / 1000.0

        # D. Carboidrati e Grassi
        # RER di base varia leggermente con l'intensità
        base_rer = 0.70 + (0.18 * intensity)
        lactate_push = min(0.25, vla_prod * 0.15)
        final_rer = min(1.0, max(0.7, base_rer + lactate_push))
        cho_pct = (final_rer - 0.7) / 0.3
        
        kcal_h = kcal_min * 60
        g_cho_h = ((kcal_min * cho_pct) / 4.0) * 60
        
        # Aggiunta costo anaerobico sopra soglia (Accumulo)
        # Qui usiamo la massa attiva specifica dello sport
        if net_balance > 0:
            g_cho_h += (net_balance * subject.weight_kg * active_mass_pct * 0.09 * 60)
            
        g_fat_h = max(0, (kcal_h - (g_cho_h * 4)) / 9)

        # E. Stima Passo Corsa (Opzionale, solo per riferimento)
        # Conversione approssimativa Watt (Stryd) -> Passo al km
        # Formula empirica: 1.04 kcal/kg/km costo energetico
        pace_label = ""
        if subject.sport == SportType.RUNNING and w > 0:
            # W/kg
            wkg = w / subject.weight_kg
            # Stima velocità km/h da W/kg (Stryd formula approx: Speed = W/kg / 1.04 * 3.6 ? No, più semplice)
            # 1 Watt/kg ~ 210 m/min ? No.
            # Usiamo formula inversa costo energetico:
            # Speed (m/min) = VO2 (ml/min/kg) / 0.2
            # VO2 = w * 0.01433 / eff / weight * 1000 / 4.85
            speed_m_min = (vo2_demand_ml / subject.weight_kg) / 0.2
            if speed_m_min > 0:
                pace_min_km = 1000 / speed_m_min
                mm = int(pace_min_km)
                ss = int((pace_min_km - mm) * 60)
                pace_label = f"{mm}:{ss:02d}"

        results.append({
            "watts": w,
            "pace": pace_label, # Nuova colonna utile per la corsa
            "la_prod": vla_prod,
            "la_comb": vla_comb,
            "net_balance": net_balance,
            "g_cho_h": g_cho_h,
            "g_fat_h": g_fat_h,
            "vo2_demand_l": vo2_demand_l,
            "vo2_uptake_l": vo2_uptake_l
        })
        
    df = pd.DataFrame(results)
    
    # 6. Calcolo MLSS
    mlss = 0
    try:
        df_valid = df[df['watts'] > 50]
        idx_mlss = (df_valid['net_balance']).abs().idxmin()
        mlss = df.loc[idx_mlss, 'watts']
    except:
        mlss = 0
        
    return df, mlss

# --- 7. SOLVER INVERSO (CALIBRAZIONE) ---

def find_vo2max_from_ftp(ftp_target, weight, vlamax_guess, sport_type):
    """
    Trova il VO2max per una data FTP.
    Include un 'pavimento' basato sul costo energetico minimo.
    """
    from data_models import Sex, MenstrualPhase
    
    # 1. Calcolo Minimo Teorico (Floor)
    # Non puoi avere un VO2max inferiore a quello che usi per pedalare alla FTP!
    eff = 0.23 if sport_type.name == 'CYCLING' else 0.21
    kcal_min_ftp = (ftp_target * 0.01433) / eff
    min_liters = kcal_min_ftp / 5.0 # ipotizzando efficienza metabolica max
    min_vo2_abs = (min_liters * 1000 / weight) * 1.02 # +2% margine
    
    # Range Ricerca
    low = min_vo2_abs
    high = 90.0
    tolerance = 0.2
    
    # Dummy Subject per simulazione
    dummy_subj = Subject(
        weight_kg=weight, vo2_max=60, vlamax=vlamax_guess, sport=sport_type,
        # Parametri default obbligatori per evitare errori
        height_cm=175, body_fat_pct=0.15, sex=Sex.MALE, glycogen_conc_g_kg=15.0, 
        uses_creatine=False, menstrual_phase=MenstrualPhase.NONE, 
        vo2max_absolute_l_min=(60 * weight) / 1000, muscle_mass_kg=None
    )
    
    found_vo2 = low
    
    # Bisezione
    iterations = 0
    while (high - low) > tolerance and iterations < 20:
        mid_vo2 = (low + high) / 2
        dummy_subj.vo2_max = mid_vo2
        dummy_subj.vo2max_absolute_l_min = (mid_vo2 * weight) / 1000
        
        _, mlss_calc = simulate_mader_curve(dummy_subj)
        
        if mlss_calc < ftp_target:
            low = mid_vo2 # Serve più motore
        else:
            high = mid_vo2 # Motore troppo grosso
            
        iterations += 1
        found_vo2 = mid_vo2
        
    return round(found_vo2, 1)

def find_vlamax_from_short_test(short_power, duration_min, weight, vo2max_known, sport_type):
    """
    Trova la VLaMax basandosi su una prestazione massimale breve.
    Include limiti di sicurezza per evitare valori non fisiologici.
    """
    # Limiti fisiologici
    VLA_MIN_LIMIT = 0.25
    VLA_MAX_LIMIT = 1.0
    MAX_LACTATE_TOLERANCE = 18.0 # mmol/L accumulabili max
    
    eff = 0.23 if sport_type.name == 'CYCLING' else 0.21
    
    # 1. Calcolo Energetico
    kcal_demand_min = (short_power * 0.01433) / eff
    
    # Contributo Aerobico (VO2 medio nel test ~95% del max)
    avg_vo2_l_min = (vo2max_known * weight / 1000.0) * 0.95
    kcal_aerobic_min = avg_vo2_l_min * 5.0 # kcal/L ossigeno
    
    # Gap Anaerobico
    kcal_gap_total = (kcal_demand_min - kcal_aerobic_min) * duration_min
    
    # Se il gap è negativo o nullo, significa che il VO2max basta e avanza.
    # In questo caso l'atleta è "Tutto Motore", ma la VLaMax non può essere 0.
    # Ritorniamo il minimo fisiologico.
    if kcal_gap_total <= 0:
        return VLA_MIN_LIMIT
        
    # 2. Iterazione Bisezione
    low = VLA_MIN_LIMIT
    high = VLA_MAX_LIMIT
    found_vla = 0.5
    
    for _ in range(15):
        mid_vla = (low + high) / 2
        
        # Stimiamo accumulo con questa VLaMax
        # Intensità relativa
        vo2_demand_l = kcal_demand_min / 4.85
        intensity = vo2_demand_l / (vo2max_known * weight / 1000.0)
        
        # Mader Production (Force intensity >= 1.05 for short max effort simulation)
        calc_intensity = max(1.05, intensity)
        raw_prod = (mid_vla * 60) * (calc_intensity ** 3)
        vla_prod_rate = raw_prod * 0.07
        
        # Clearance (Max capacity during effort)
        vla_comb_rate = 0.0225 * vo2max_known
        
        net_accumulation = (vla_prod_rate - vla_comb_rate) * duration_min
        
        if net_accumulation > MAX_LACTATE_TOLERANCE:
            high = mid_vla # Troppo accumulo -> Riduci VLa
        else:
            low = mid_vla  # Poco accumulo -> Alza VLa
            
        found_vla = mid_vla
        
    return round(found_vla, 2)




















