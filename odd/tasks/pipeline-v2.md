# Pipeline v2 — canónico de venues, multi-fecha y corrida diaria

**Estado:** Completo (2026-10-13) · **Repo:** local (`cartelera-mdp`, sin remoto) · **Fecha:** 2026-10-13
**Contexto:** Fase 1 del MVP (`docs/mvp.md`); extiende el spike (`odd/tasks/spike-extraccion.md`, `REPORT.md`).

## Objetivo

1. **Canónico de venues:** registry con alias en `data/venues.json` + `lib/venues.py`, integrado al dedupe.
2. **Multi-fecha:** expandir eventos con varias fechas a `occurrences` (Articket `unica_fecha=false` vía página de detalle; rangos municipal según regla documentada).
3. **Corrida robusta:** no pisar datos buenos si un collector falla; `run_pipeline.py` + `scripts/daily.sh` + README.

## Problema

El spike dejó tres deudas: 38 nombres crudos ≈ 30 lugares reales (13 clusters dependen de alias a mano), multi-fecha expone solo la primera fecha, y el runner sobrescribe `data/` aunque un collector falle.

## Alcance

- **In:** registry + integración dedupe; `occurrences` en schema + expansiones; dedupe por intersección de ocurrencias; runner robusto + script diario; tests; refresh de data + REPORT v2.
- **Out:** web/deploy, activación del schedule (se decide al deploy), fuentes nuevas, ToS.

## Restricciones

- Fetch educado: ~1 req/s, UA identificable, ≤ ~30 requests en la corrida. Solo lectura sobre sitios externos.
- No instalar cron/systemd en la máquina: solo script + instrucciones.
- Código en inglés; docs (README/REPORT) en español, tono directo.

## Criterios de aceptación

- [x] Registry (~30 venues con alias) usado por el dedupe (sin lista hardcodeada).
- [x] Multi-fecha expandido a `occurrences` con reglas documentadas y tests.
- [x] Dedupe matchea por intersección de ocurrencias (fallback a fecha simple).
- [x] Fallo parcial → no pisa outputs, exit ≠ 0, evidencia en `data/`; éxito → `data/last_run.json`.
- [x] `scripts/daily.sh` + README con ejemplo de schedule.
- [x] Tests verdes + corrida live con números reportados (antes/después).

## Tareas

- [x] **T1** — `data/venues.json` + `lib/venues.py` (normalización y resolución por alias) + tests.
- [x] **T2** — Integrar registry al dedupe (migrar los 5 alias hardcodeados) + tests.
- [x] **T3** — `occurrences` en schema + expansión de rangos municipal (regla documentada) + tests.
- [x] **T4** — Enriquecer Articket multi-fecha desde la página de detalle (JSON-LD/HTML) + tests.
- [x] **T5** — Dedupe por ocurrencias + tests.
- [x] **T6** — Runner robusto (rename a `run_pipeline.py`) + `scripts/daily.sh` + README + test del camino de fallo parcial.
- [x] **T7** — Refresh de `data/` + REPORT.md v2 (números antes/después).

## Verificación

- `python3 -m pytest tests/ -q`
- `python3 run_pipeline.py` — corrida live; números observados.

## Delivery

Local (sin remoto). ~4 commits por work unit; tests verdes en cada uno. Sin PR.

## Presupuesto

Heurística ~500–700 líneas autoradas. Sin UI.

## Evidencia / Progreso

- **T1 (2026-10-13):** `data/venues.json` con 30 venues y los alias observados en `data/raw/*.json`; `lib/venues.py` (`normalize_name`, `resolve`, `venue_key`) + 23 tests en `tests/test_venues.py`. Cobertura sobre el corpus: 42 strings crudos distintos → 0 sin resolver. Sheraton: el hall "Auditorium Victoria Ocampo" (Alem 4221) mapea al Sheraton; Villa Victoria (Matheu 1851) queda como venue aparte.
- **T2 (2026-10-13):** el dedupe usa `venue_key` (id canónico o nombre normalizado) y se eliminó el mapa hardcodeado de 5 alias. `pytest tests/ -q`: 68 verdes. Nuevo cluster habilitado por el registry: Sheraton municipal ↔ Articket (no resolvía con el mapa viejo).
- **T3 (2026-10-13):** `occurrences` + `recurrence_unknown` en `lib/schema.py`; `lib/occurrences.py` (regla: expandir por día de semana listado; rango sin recurrencia → `occurrences: []` + flag; día único siempre es fecha exacta). `collectors/municipal.py` segmenta "desde/hasta + días" y expande. Dry-run sobre el corpus real: 101 eventos → 11 multi-fecha, 130 fechas en total, 0 rangos sin info de recurrencia. Tests: `tests/test_occurrences.py` + `tests/test_municipal.py`.
- **T4 (2026-10-13):** `enrich_occurrences()` en `collectors/muchticket.py` baja el detalle de los 2 eventos `unica_fecha=false` (1 req/s). Fuente primaria: `<select name="fechas_evento">` (lista completa de funciones); fallback: JSON-LD `schema.org/Event` (solo startDate/endDate → primera fecha + `multi_date_incomplete`). Verificado en vivo: el JSON-LD de Articket NO trae todas las fechas (el select sí), documentado en `lib/occurrences.py`.
- **T5 (2026-10-13):** el dedupe agrupa por venue canónico y matchea por intersección de `occurrences` (fallback a `date_start` cuando algún lado no tiene fechas conocidas); el cluster expone `venue`, `venue_name` y `dates` (unión). Sin regresiones: sobre el dataset viejo (sin occurrences) reproduce exactos los 59 pares / 41 clusters del spike. Tests nuevos: intersección con starts distintos, disjunción con start igual, fallback. `pytest tests/ -q`: 101 verdes.
- **T6 (2026-10-13):** `run_spike.py` → `run_pipeline.py`: colecta TODAS las fuentes antes de escribir; si alguna falla → `data/raw/<fuente>.error.json`, outputs intactos, exit ≠ 0. Éxito: escrituras atómicas (tmp+rename) + `data/last_run.json` (timestamp UTC, counts por fuente, totales, clusters, occurrences, venues, duración). `scripts/daily.sh` (log en `logs/daily.log`, `logs/` gitignoreado) + README con ejemplos cron/systemd (nada instalado). Tests: fallo parcial con collector inyectado (outputs intactos, exit ≠ 0) y éxito (last_run + sin `.tmp`); script verificado con venv falso (propaga exit code y appendea log). `pytest tests/ -q`: 103 verdes.
- **T7 (2026-10-13):** corrida live con `run_pipeline.py`: 197 normalizados → **146 únicos** (antes 147), 41 clusters / 60 pares (antes 59), 13 multi-fecha → 234 fechas totales, 2 enriquecidos por detalle, 0 `recurrence_unknown` / 0 `multi_date_incomplete`, 197/197 venues resueltos, 36.5s, ~18 requests. Diff de pares vs spike: 0 perdidos, 1 agregado (Tan Biónica 22/11 por intersección de occurrences). `data/` refrescado + `REPORT.md` v2 con antes/después. Un bug real apareció en la primera corrida (weekdays no serializables en el raw) y se corrigió con test de regresión (`cd5e33e`): la política del runner dejó los outputs intactos y salió ≠ 0.

## Cierre

- **Verificación independiente:** VERIFIED (2026-10-13/14 UTC). Conteos exactos (197 → 146 únicos; 41 clusters / 60 pares; 234 occurrences), registry de 30 venues resolviendo los 42 strings crudos (0 sin resolver), multi-fecha confirmado contra páginas en vivo (select `fechas_evento` de Articket; expansión municipal por día de semana), 0 pares de dedupe perdidos (1 agregado: Tan Biónica 22/11), runner robusto probado con test + incidente real, sin atribución AI.
- **Corrección post-verificación:** los rangos de un día ahora siempre rinden su fecha (3 eventos recuperados: 11/11/2026, 07/12/2026, 29/01/2029) y las expansiones vacías se marcan `recurrence_unknown`. Commits `b525c56` + `375d670`; occurrences 234 → 237; tests 104 → 107; spot check del parent OK.
- **Follow-ups:** verificar tope de paginación municipal en temporada alta (enero); ToS de MuchTicket; multi-fecha transitivo documentado en REPORT §3.
