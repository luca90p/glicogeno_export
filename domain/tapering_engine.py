import pandas as pd

from data_models import Subject, GlycogenState


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
    if current_muscle_glycogen > max_physiological_limit:
        current_muscle_glycogen = max_physiological_limit

    liver_fill_factor = 1.0
    if subject.filling_factor <= 0.6:
        liver_fill_factor = 0.6
    if subject.glucose_mg_dl is not None:
        if subject.glucose_mg_dl < 70:
            liver_fill_factor = 0.2
        elif subject.glucose_mg_dl < 85:
            liver_fill_factor = min(liver_fill_factor, 0.5)

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
    LIVER_DRAIN_H = 4.0  # Consumo cervello/organi (g/h)
    NEAT_DRAIN_H = (1.0 * subject.weight_kg) / 16.0  # NEAT spalmato sulle 16h di veglia (g/h)

    # Ciclo sui Giorni
    for day_idx, day in enumerate(days_data):
        date_label = day['date_obj'].strftime("%d/%m")

        # Parsing Orari
        sleep_start = day['sleep_start'].hour + (day['sleep_start'].minute / 60)
        sleep_end = day['sleep_end'].hour + (day['sleep_end'].minute / 60)
        # Gestione notte (es. 23:00 -> 07:00). Se sleep_start > sleep_end, scavalca la mezzanotte

        work_start = day['workout_start'].hour + (day['workout_start'].minute / 60)
        work_dur_h = day['duration'] / 60.0
        work_end = work_start + work_dur_h

        total_cho_input = day['cho_in']

        # Calcolo Ore di Veglia (Feeding Window) per distribuire il cibo
        waking_hours = 0
        for h in range(24):
            is_sleeping = False
            if sleep_start > sleep_end:  # Scavalca notte (es 23-07)
                if h >= sleep_start or h < sleep_end:
                    is_sleeping = True
            else:
                if sleep_start <= h < sleep_end:
                    is_sleeping = True

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
                if h >= sleep_start or h < sleep_end:
                    is_sleeping = True
            else:
                if sleep_start <= h < sleep_end:
                    is_sleeping = True

            if is_sleeping:
                status = "SLEEP"

            # Check Allenamento (Prioritario sul sonno se configurato male)
            if work_start <= h < work_end:
                status = "WORK"

            # --- BILANCIO ORARIO ---
            hourly_in = 0
            hourly_out_liver = LIVER_DRAIN_H  # Sempre attivo (cervello)
            hourly_out_muscle = 0

            if status == "SLEEP":
                hourly_in = 0  # Non mangi mentre dormi

            elif status == "WORK":
                hourly_in = 0  # Assumiamo integrazione separata o nulla nel tapering
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
                liver_share = 0.15  # Il fegato contribuisce sempre un po' sotto sforzo
                hourly_out_muscle = g_cho_work * (1 - liver_share)
                hourly_out_liver += g_cho_work * liver_share

            elif status == "REST":
                hourly_in = cho_rate_h
                hourly_out_muscle = NEAT_DRAIN_H  # Piccolo consumo per muoversi

            # --- CALCOLO NETTO ---
            net_flow = hourly_in - (hourly_out_liver + hourly_out_muscle)

            # Applicazione ai serbatoi (Ripartizione)
            if net_flow > 0:
                # REFILLING (Priorità Muscolo 70/30)
                efficiency = day['sleep_factor']
                real_storage = net_flow * efficiency

                to_muscle = real_storage * 0.7
                to_liver = real_storage * 0.3

                # Overflow Logic
                if curr_muscle + to_muscle > MAX_MUSCLE:
                    overflow = (curr_muscle + to_muscle) - MAX_MUSCLE
                    to_muscle -= overflow
                    to_liver += overflow  # Il fegato prova a prenderlo (lipogenesi dopo)

                curr_muscle = min(MAX_MUSCLE, curr_muscle + to_muscle)
                curr_liver = min(MAX_LIVER, curr_liver + to_liver)

            else:
                # DRAINING
                abs_deficit = abs(net_flow)

                if status == "WORK":
                    # Il consumo è già diviso in hourly_out_...
                    # Ma hourly_in potrebbe coprire parte. Semplifichiamo:
                    # Ricalcolo flussi separati con intake
                    # Intake supporta prima il fegato (glicemia)
                    liver_balance = (hourly_in) - hourly_out_liver
                    if liver_balance < 0:
                        curr_liver += liver_balance  # Scende
                    else:
                        curr_liver += liver_balance  # Sale o pari

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
