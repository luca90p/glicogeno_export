### 1) Introduzione cartelle “ui/” e “domain/”

**Spostamento (senza rimozione di codice):**

- `ui/sidebar.py`
  - Gestione profilo atleta, sport, peso, VO2max, soglie.
- `ui/tab_profile.py`
  - Contenuto del Tab 1 (profilo & metabolismo).
- `ui/tab_tapering.py`
  - Contenuto del Tab 2 (diario tapering).
- `ui/tab_simulation.py`
  - Contenuto del Tab 3 (simulazione gara & strategia).

**Nota:** `app_glicogeno.py` rimane come entry-point e importa funzioni da questi moduli.

### 2) Separazione utilities in moduli dedicati

Senza rimuovere `utils.py`, si possono estrarre gradualmente moduli dedicati:

- `parsers/fit.py` → funzioni per FIT (`process_fit_data`, `parse_fit_file_wrapper`).
- `parsers/metabolic.py` → parsing report metabolico.
- `parsers/zwo.py` → parsing ZWO.
- `plots/fit_altair.py` → `create_fit_plot`.
- `math/` o `calculations/` → funzioni di supporto (es. `calculate_normalized_power`).

**Nota:** `utils.py` può continuare ad esportare le stesse funzioni, ma delegandole ai nuovi moduli (compatibilità retroattiva).

### 3) Consolidamento FIT parser senza rimozioni

`fit_processor.py` non va rimosso. Si può:

- Lasciarlo come “legacy backend Matplotlib”.
- Oppure aggiungere un flag di configurazione per scegliere il renderer (Altair vs Matplotlib).

In questo modo, nessun file è rimosso, ma si chiarisce l’uso.

### 4) Organizzazione della logica di dominio

Opzionale ma consigliato:

- Creare `domain/metabolism_engine.py` e spostare dentro `simulate_metabolism` e `calculate_minimum_strategy`.
- Creare `domain/tapering_engine.py` e spostare `calculate_hourly_tapering`.

`logic.py` può rimanere e fare da wrapper verso i nuovi moduli.

## Esempio di struttura target (senza eliminare nulla)

```
.
├── app_glicogeno.py
├── data_models.py
├── logic.py
├── utils.py
├── fit_processor.py
├── ui/
│   ├── sidebar.py
│   ├── tab_profile.py
│   ├── tab_tapering.py
│   └── tab_simulation.py
├── domain/
│   ├── metabolism_engine.py
│   └── tapering_engine.py
├── parsers/
│   ├── fit.py
│   ├── metabolic.py
│   └── zwo.py
└── plots/
    └── fit_altair.py


