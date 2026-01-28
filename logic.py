import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState, GlycogenState, IntakeMode, SportType

from domain.metabolism_engine import simulate_metabolism as _simulate_metabolism
from domain.metabolism_engine import calculate_minimum_strategy as _calculate_minimum_strategy
from domain.tapering_engine import calculate_hourly_tapering as _calculate_hourly_tapering

# --- 1. FUNZIONI HELPER ---

def get_concentration_from_vo2max(vo2_max):
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    return max(12.0, min(26.0, conc))

def calculate_rer_polynomial(intensity_factor):
    """
    Calcola il Respiratory Exchange Ratio basato sull'intensità relativa (IF).
    Modello polinomiale standard per stimare il consumo di substrati.
    """
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
    return _calculate_hourly_tapering(subject, days_data, start_state=start_state)

# --- 3. SIMULAZIONE METABOLICA (NO MADER - SOLO CROSSOVER) ---

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        custom_max_exo_rate=None, mix_type_input=ChoMixType.GLUCOSE_ONLY, 
                        intensity_series=None, metabolic_curve=None, 
                        intake_mode=IntakeMode.DISCRETE, intake_cutoff_min=0, variability_index=1.0):
    return _simulate_metabolism(
        subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct,
        tau_absorption, subject_obj, activity_params,
        oxidation_efficiency_input=oxidation_efficiency_input,
        custom_max_exo_rate=custom_max_exo_rate, mix_type_input=mix_type_input,
        intensity_series=intensity_series, metabolic_curve=metabolic_curve,
        intake_mode=intake_mode, intake_cutoff_min=intake_cutoff_min,
        variability_index=variability_index
    )

# --- 4. CALCOLO REVERSE STRATEGY (AGGIORNATA SENZA MADER) ---

def calculate_minimum_strategy(tank, duration, subj, params, curve_data, mix_type, intake_mode, intake_cutoff_min=0, variability_index=1.0, intensity_series=None):
    """
    Calcola la strategia nutrizionale minima necessaria.
    Itera simulazioni aumentando l'intake finché i serbatoi non rimangono sopra la soglia di sicurezza.
    """
    return _calculate_minimum_strategy(
        tank, duration, subj, params, curve_data, mix_type, intake_mode,
        intake_cutoff_min=intake_cutoff_min,
        variability_index=variability_index,
        intensity_series=intensity_series
    )
