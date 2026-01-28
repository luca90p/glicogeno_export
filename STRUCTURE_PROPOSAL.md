# Proposta di ristrutturazione (senza rimuovere codice)

Questa proposta descrive come migliorare l'organizzazione del progetto **senza eliminare o tagliare alcuna parte di codice esistente**. L’obiettivo è solo **spostare** o **incapsulare** le funzionalità in moduli più chiari, mantenendo l’attuale comportamento.

## Obiettivi

- Mantenere invariato il comportamento dell’app.
- Separare UI, dominio e parsing per rendere il codice più manutenibile.
- Preparare una struttura in cui i moduli siano riusabili e testabili.
- Ridurre la duplicazione (es. FIT parsing) senza cancellare alcun file.

## Stato attuale (sintesi)

- `app_glicogeno.py`: UI + orchestrazione + logiche di flusso, molto esteso.
- `logic.py`: motore di simulazione e calcoli principali.
- `data_models.py`: enum e dataclass di dominio.
- `utils.py`: parsing FIT/ZWO/Metabolic + plotting + funzioni di supporto.
- `fit_processor.py`: parser FIT alternativo e grafici Matplotlib (duplicazione potenziale).

## Proposta (a passi, senza tagli)

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
```

## Strategia di migrazione sicura

1. **Fase 1:** Creare i nuovi moduli e copiarvi le funzioni, mantenendo le vecchie importazioni.
2. **Fase 2:** In `utils.py`/`logic.py`, trasformare le funzioni in wrapper che chiamano i nuovi moduli.
3. **Fase 3:** Aggiornare `app_glicogeno.py` a usare i moduli nuovi.
4. **Fase 4:** Aggiungere test di regressione (se disponibili).

## Vantaggi

- UI più leggibile e modulare.
- Logica facilmente testabile.
- Riduzione della “mescolanza” tra parsing/plotting/strategia metabolica.
- Maggiore capacità di estensione futura.

---

Se vuoi, posso implementare questi spostamenti in modo progressivo, **senza eliminare nulla**, e mantenendo la compatibilità con l’attuale API interna.
