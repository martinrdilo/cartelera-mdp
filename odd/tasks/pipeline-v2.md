# Pipeline v2 — canónico de venues, multi-fecha y corrida diaria

**Estado:** En curso · **Repo:** local (`cartelera-mdp`, sin remoto) · **Fecha:** 2026-10-13
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

- [ ] Registry (~30 venues con alias) usado por el dedupe (sin lista hardcodeada).
- [ ] Multi-fecha expandido a `occurrences` con reglas documentadas y tests.
- [ ] Dedupe matchea por intersección de ocurrencias (fallback a fecha simple).
- [ ] Fallo parcial → no pisa outputs, exit ≠ 0, evidencia en `data/`; éxito → `data/last_run.json`.
- [ ] `scripts/daily.sh` + README con ejemplo de schedule.
- [ ] Tests verdes + corrida live con números reportados (antes/después).

## Tareas

- [ ] **T1** — `data/venues.json` + `lib/venues.py` (normalización y resolución por alias) + tests.
- [ ] **T2** — Integrar registry al dedupe (migrar los 5 alias hardcodeados) + tests.
- [ ] **T3** — `occurrences` en schema + expansión de rangos municipal (regla documentada) + tests.
- [ ] **T4** — Enriquecer Articket multi-fecha desde la página de detalle (JSON-LD/HTML) + tests.
- [ ] **T5** — Dedupe por ocurrencias + tests.
- [ ] **T6** — Runner robusto (rename a `run_pipeline.py`) + `scripts/daily.sh` + README + test del camino de fallo parcial.
- [ ] **T7** — Refresh de `data/` + REPORT.md v2 (números antes/después).

## Verificación

- `python3 -m pytest tests/ -q`
- `python3 run_pipeline.py` — corrida live; números observados.

## Delivery

Local (sin remoto). ~4 commits por work unit; tests verdes en cada uno. Sin PR.

## Presupuesto

Heurística ~500–700 líneas autoradas. Sin UI.

## Evidencia / Progreso

_(se actualiza al cierre de cada tarea)_
