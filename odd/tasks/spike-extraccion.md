# Spike de extracción — eventos musicales Mar del Plata

**Estado:** En curso · **Repo:** local (`cartelera-mdp`, sin remoto) · **Fecha:** 2026-10-13

## Objetivo

Probar con datos reales que se pueden extraer, normalizar y deduplicar eventos musicales de Mar del Plata desde las 3 fuentes "fáciles" relevadas en la investigación previa:

1. **Municipal (EMTUR)** — agenda oficial; ASP server-rendered; filtros GET (`tipo=11/16/19`, paginado).
2. **MuchTicket** — Articket + CultuTickets; JSON abierto `GET /obtener_eventos/?cantidad_eventos=N`.
3. **ClubTri** — agenda de un lugar; HTML plano; fechas en español sin año.

## Problema

No existe una cartelera music-first de MDP con links de compra. Antes de invertir en producto hay que medir cobertura real, calidad de datos y esfuerzo de dedupe: ese es el riesgo del proyecto, no la UI.

## Alcance

- **Incluye:** collectors de las 3 fuentes, esquema normalizado común, dedupe (fingerprint + fuzzy) y reporte de cobertura con números reales.
- **Excluye:** UI, base de datos, deploy y las fuentes duras (Plateanet, Bandsintown, Bombo, Instagram) — fases posteriores.

## Restricciones

- Python 3 + `.venv` local; dependencias livianas (requests/httpx, beautifulsoup4, rapidfuzz, pytest).
- Fetch educado: ~1 req/s, UA identificable, pocas decenas de requests. Solo lectura sobre sitios externos.
- Código en inglés; docs (README/REPORT) en español, tono directo.

## Criterios de aceptación

- [ ] 100+ eventos reales extraídos entre las 3 fuentes (JSON normalizado).
- [ ] Esquema único documentado (título, lugar, fecha, hora, precio, link de compra, fuente).
- [ ] Dedupe con ejemplos verificables (evento presente en ≥2 fuentes detectado).
- [ ] REPORT.md con cobertura, calidad de datos y limitaciones.

## Tareas

- [ ] **T1** — Collector municipal (`tipo` 11/16/19, ISO-8859-1, paginación, fechas dd/mm/yyyy).
- [ ] **T2** — Collector MuchTicket (Articket + CultuTickets; filtro "Mar del Plata" en `lugar`).
- [ ] **T3** — Collector ClubTri (HTML; "Mié 14 de Octubre" → ISO con inferencia de año).
- [ ] **T4** — Normalizador + esquema común (tests primero en parsing de fechas).
- [ ] **T5** — Dedupe (fingerprint venue+fecha + similitud de título / match por slug de compra).
- [ ] **T6** — REPORT.md (cobertura, solapamientos, limitaciones) + README de uso.

## Verificación

- `python3 -m pytest tests/ -q` — lógica pura (fechas, dedupe).
- `python3 run_spike.py` — corrida real end-to-end; evidencia en `data/` + REPORT.md.

## Delivery

Local (repo nuevo, sin remoto). Commits por work unit (2 unidades). Estrategia de PR diferida hasta que exista remoto (`ask-on-risk`).

## Presupuesto

Heurística ~400–600 líneas autoradas, sin UI. Spike acotado.

## Evidencia / Progreso

_(se actualiza al cierre de cada tarea)_
