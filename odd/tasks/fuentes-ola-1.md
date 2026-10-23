# Fuentes ola 1 — Venti, Ticketek, Bombo y Punto MDP

Objective: sumar cuatro fuentes nuevas de eventos musicales de Mar del Plata al pipeline, sin duplicar eventos en el sitio.
Branch: `feat/fuentes-ola-1`. Delivery: work-unit commits. Test runner: `.venv/bin/python -m pytest tests/ -q`.

## Specs

- **S1**: Agregar al pipeline las fuentes de la ola 1: **Venti**, **Ticketek**, **Bombo** y **Punto Mar del Plata**. Cada fuente expone `collect() -> list[dict]` y `normalize(records) -> list[Event]`, como las fuentes existentes.
- **S2**: "tenemos que tener en cuenta que hay que filtrar porque puede haber repetidos. Entonces, tenemos que tener eso en cuenta: que no haya un evento duplicado en nuestra aplicación." El pipeline debe resolver el mismo evento publicado por dos fuentes en un solo cluster, y el sitio no debe renderizar dos filas para el mismo evento (mismo venue, misma fecha, mismo título normalizado).
- **S3**: No romper las fuentes existentes (municipal, Articket, CultuTickets, Club TRI) ni la suite actual: 175 tests en verde antes de empezar.
- **S4**: Solo lectura, user-agent `cartelera-mdp-pipeline/0.2 (local research)`, ~1 req/s. Los tests no pegan a la red: usan fixtures de `tests/fixtures/`.
- **S5**: Actualizar `data/venues.json` con los venues/alias que aparecen en las fuentes nuevas, y `build_site.py` con las etiquetas de fuente y la prioridad de campos.

## Tasks

- **T1** ✅ Venti collector: `collectors/venti.py` + `tests/test_venti.py`. API JSON, filtro MDP por coordenadas, fecha UTC→hora local. Route: delegated. Commit `f1b774d`. Spec: S1, S4.
- **T2** ✅ Ticketek collector: `collectors/ticketek.py` + `tests/test_ticketek.py`. Búsqueda JSON + nodo por show; fechas desde `google_structured_data`. Route: delegated. Commit `eaa5b6f`. Spec: S1, S4.
- **T3** ✅ Bombo collector: `collectors/bombo.py` + `tests/test_bombo.py`. Búsqueda JSON + detalle JSON-LD para venue/precio. Route: delegated. Commit `6ee59bc`. Spec: S1, S4.
- **T4** ✅ Punto collector: `collectors/punto.py` + `tests/test_punto.py`. API JSON paginada + detalle JSON-LD para link de venta. Route: delegated. Commit `69cafda`. Spec: S1, S4.
- **T5** ✅ Dedupe/venues/site: `data/venues.json` (40 venues), `lib/dedupe.py` (slugs nuevos + contención de tokens + prefijo de artista), `build_site.py` (labels/prioridad + guard final), tests. Route: inline (parent). Commit `b713182`. Spec: S2, S5.
- **T6** ✅ Runner + docs + corrida real: `run_pipeline.py` (7 módulos / 8 feeds), `README.md`, `REPORT.md`, verificación end-to-end. Route: inline (parent). Spec: S1, S2, S3.

## Log

- **L1** (request original, verbatim): "Necesito que podamos agregar más fuentes de anuncios de eventos a esta aplicación. Tenemos que encontrar más fuentes de ventas de entrada y más fuentes de publicación de eventos musicales en Mar del Plata. La necesito poblar. Podremos hacer una investigación de las posibles fuentes que podremos agregar. Primero, listame cuáles son las actuales, cuáles son las fuentes. A partir de eso, fijate si explorás e investigás a ver si hay otras fuentes que podamos agregar. ¿Qué te parece? Acordate que es todo de Mar del Plata."
- **L2** (aprobación, verbatim): "Dale, me parece bien. Vamos con la ola 1. Además, tenemos que tener en cuenta que hay que filtrar porque puede haber repetidos. Entonces, tenemos que tener eso en cuenta: que no haya un evento duplicado en nuestra aplicación. Y después, si hacemos la ola 2, bueno, está bien. La ola 2 también y la ola 3 también, pero vamos por la 1, ¿ok?"
- **L3**: Baseline 175 tests passed (2026-10-22). Fixtures reales guardados en `tests/fixtures/` para las cuatro fuentes.
- **L4**: Investigación previa: Venti `api.venti.live/api/home/events` (13 MDP, ciudad "Costa Argentina" → filtrar por coordenadas); Ticketek `prod-cms-search.ticketek.com.ar/api/1.1/search/mar%20del%20plata` (9 funciones MDP, nodo con `google_structured_data`); Bombo `wearebombo.com/api/eventos/buscar?q=mar del plata` (8 MDP, detalle JSON-LD); Punto `puntomardelplata.com/api/actividades?...&categoria=1` (84 eventos de música, 7 páginas, detalle JSON-LD con offers).
- **L5**: Corrida final 2026-10-23T00:26Z: 298 crudos → 298 normalizados → 187 únicos; 81 clusters (192 involucrados); 295/298 venues resueltos; duración 482 s. `build_site.py`: 187 filas, 32 del finde, 0 tripletas duplicadas (venue + título normalizado + fecha). Suite: 253 tests en verde.
