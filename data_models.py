from enum import Enum
from dataclasses import dataclass

class Sex(Enum):
    MALE = "Uomo"
    FEMALE = "Donna"

class TrainingStatus(Enum):
    SEDENTARY = (13.0, "Sedentario / Principiante")
    RECREATIONAL = (16.0, "Attivo / Amatore")
    TRAINED = (19.0, "Allenato (Intermedio)")
    ADVANCED = (22.0, "Avanzato / Competitivo")
    ELITE = (25.0, "Elite / Pro")

    def __init__(self, val, label):
        self.val = val
        self.label = label

class SportType(Enum):
    """
    Coefficienti di Massa Muscolare Attiva (% della massa muscolare totale).
    
    --- NOTE PER LO SVILUPPATORE (RIF. BIBLIOGRAFICI) ---
    I valori sono stati ridotti rispetto alle stime generiche per allinearsi al modello 
    fisiologico rigido di B. Rapoport ("Metabolic Factors Limiting Performance in Marathon Runners", 2010).
    
    Fonte Primaria: Rapoport BI (2010) PLoS Comput Biol 6(10).
    Supporto DEXA/MRI:
    1. Heymsfield et al. (1990): Massa muscolare appendicolare (gambe) è ~21.4% della massa corporea totale.
    2. Wang et al. (1999) & Levine et al. (2000): Confermano che la massa attiva locomotoria è una frazione 
       specifica, non l'intera massa magra.
       
    Valori Precedenti (Ottimistici) vs Nuovi (Prudenziali/Rapoport):
    - Cycling: 0.63 -> 0.50 (Isolamento arti inferiori, tronco statico)
    - Running: 0.75 -> 0.55 (Gambe + Core/Stabilizzatori, ma esclude upper body passivo)
    - Triathlon: 0.85 -> 0.65 (Media ponderata)
    
    Questo previene la sovrastima del serbatoio di glicogeno (Safety First).
    -----------------------------------------------------
    """
    CYCLING = (0.50, "Ciclismo (Prevalenza arti inferiori)")
    RUNNING = (0.55, "Corsa (Arti inferiori + Core)")
    TRIATHLON = (0.65, "Triathlon (Multidisciplinare)")
    XC_SKIING = (0.95, "Sci di Fondo (Whole Body)")
    SWIMMING = (0.80, "Nuoto (Arti sup. + inf.)")

    def __init__(self, val, label):
        self.val = val
        self.label = label

class DietType(Enum):
    HIGH_CARB = (1.25, "Carico Carboidrati (Supercompensazione)", 8.0)
    NORMAL = (1.00, "Regime Normocalorico Misto (Baseline)", 5.0)
    LOW_CARB = (0.50, "Restrizione Glucidica / Low Carb", 2.5)

    def __init__(self, factor, label, ref_value):
        self.factor = factor
        self.label = label
        self.ref_value = ref_value

class FatigueState(Enum):
    RESTED = (1.0, "Riposo / Tapering (Pieno Recupero)")
    ACTIVE = (0.9, "Carico di lavoro moderato (24h prec.)")
    TIRED = (0.60, "Alto carico o Danno Muscolare (EIMD)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class SleepQuality(Enum):
    GOOD = (1.0, "Ottimale (>7h, ristoratore)")
    AVERAGE = (0.95, "Sufficiente (6-7h)")
    POOR = (0.85, "Insufficiente / Disturbato (<6h)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class MenstrualPhase(Enum):
    NONE = (1.0, "Non applicabile")
    FOLLICULAR = (1.0, "Fase Follicolare")
    LUTEAL = (0.95, "Fase Luteale (Premestruale)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class ChoMixType(Enum):
    GLUCOSE_ONLY = (1.0, 60.0, "Solo Glucosio/Maltodestrine (Standard)")
    MIX_2_1 = (1.5, 90.0, "Mix 2:1 (Maltodestrine:Fruttosio)")
    MIX_1_08 = (1.7, 105.0, "Mix 1:0.8 (High Fructose)")

    def __init__(self, ox_factor, max_rate_gh, label):
        self.ox_factor = ox_factor 
        self.max_rate_gh = max_rate_gh 
        self.label = label

class GlycogenState(Enum):
    EMPTY = (0.25, "Esausto (Post-Gara/Lungo)")
    LOW = (0.45, "Basso (Blocco Carico Intenso)")
    NORMAL = (0.60, "Normale (Routine Standard)")
    HIGH = (0.80, "Alto (Ben Nutrito/Riposato)")
    FULL = (1.00, "Supercompensato (Glicogeno Loading)") # Max teorico realistico

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class IntakeMode(Enum):
    DISCRETE = "Discretizzata (Gel / Barrette / Solidi)"
    CONTINUOUS = "Continuativa (Bevanda Isotonica / Sorsi frequenti)"

@dataclass
class Subject:
    weight_kg: float
    height_cm: float 
    body_fat_pct: float
    sex: Sex
    glycogen_conc_g_kg: float
    sport: SportType
    vo2_max: float = 55.0      # Default
    vlamax: float = 0.5        # Default
    liver_glycogen_g: float = 100.0
    filling_factor: float = 1.0 
    uses_creatine: bool = False
    menstrual_phase: MenstrualPhase = MenstrualPhase.NONE
    glucose_mg_dl: float = None
    vo2max_absolute_l_min: float = 3.5 
    muscle_mass_kg: float = None 

    @property
    def lean_body_mass(self) -> float:
        return self.weight_kg * (1.0 - self.body_fat_pct)

    @property
    def muscle_fraction(self) -> float:
        # Stima massa muscolare totale (non attiva)
        base = 0.50 if self.sex == Sex.MALE else 0.42
        if self.glycogen_conc_g_kg >= 22.0:
            base += 0.03
        return base

