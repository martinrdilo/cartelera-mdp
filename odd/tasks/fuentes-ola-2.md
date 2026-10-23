# Fuentes ola 2 — Auditorium, Teatro Colón y TuEntrada

Objective: sumar tres fuentes nuevas de la cartelera de Mar del Plata al pipeline (Auditorium, Teatro Colón y TuEntrada), sin duplicar eventos en el sitio y dejando Plateanet para la ola 3.
Branch: `feat/fuentes-ola-2` (parte de `feat/fuentes-ola-1`). Delivery: work-unit commits. Test runner: `.venv/bin/python -m pytest tests/ -q`.

## Specs

- **S1**: Agregar al pipeline las fuentes de la ola 2: **Teatro Auditorium** (`teatroauditorium.gba.gob.ar`), **Teatro Colón** (`mardelplata.gob.ar/colonprogramacion`) y **TuEntrada**. Cada fuente expone `collect() -> list[dict]` y `normalize(records) -> list[Event]`, como las fuentes existentes.
- **S2**: "Plateanet queda para la ola 3, con estrategia manual o acuerdo: está detrás de Incapsula/hCaptcha." No se agrega Plateanet como collector en esta ola; solo se conserva como seller cuando otra fuente enlaza o menciona la venta.
- **S3**: "tenemos que tener en cuenta que hay que filtrar porque puede haber repetidos... que no haya un evento duplicado en nuestra aplicación." Las fuentes nuevas participan del dedupe existente (venue canónico + fecha + título normalizado) y el sitio no renderiza dos filas para el mismo evento. Actualizar `data/venues.json` con las salas/alias que aparecen.
- **S4**: Solo lectura, user-agent `cartelera-mdp-pipeline/0.2 (local research)`, ~1 req/s. Los tests no pegan a la red: usan fixtures reales de `tests/fixtures/`.
- **S5**: No romper las fuentes existentes (municipal, Articket, CultuTickets, Club TRI, Venti, Ticketek, Bombo, Punto) ni la suite: baseline 253 tests en verde.
- **S6**: Actualizar `build_site.py` (etiquetas de fuente y prioridad de campos), `run_pipeline.py` (módulos/feeds), `README.md` y `REPORT.md`; cerrar con una corrida real y métricas observadas.

## Tasks

- **T1** ✅ Auditorium collector: `collectors/auditorium.py` + `tests/test_auditorium.py` + fixtures. 7 páginas de programación, 37 eventos, detalle para seller/gratis, salas → venues. Route: delegated (writer paralelo A). Commit `809fd25`. Spec: S1, S3, S4.
- **T2** ✅ Teatro Colón collector: `collectors/colon.py` + `tests/test_colon.py` + fixture. Página mensual HTML, 28 eventos (incluye la línea con dos horarios), precios y gratis. Route: delegated (writer paralelo B). Commit `d0a3d40`. Spec: S1, S3, S4.
- **T3** ✅ TuEntrada collector: `collectors/tuentrada.py` + `tests/test_tuentrada.py` + fixtures. Búsqueda server-rendered + sesiones en el payload de la ficha; fallback de rango sin inventar fechas. Route: delegated (writer paralelo C). Commit `7b54eea`. Spec: S1, S3, S4.
- **T4** ✅ Integración: `data/venues.json` (salas Auditorium, Polideportivo, Teatro Enrique Carreras), `run_pipeline.py`, tests de venues. Route: inline (parent). Commit de integración. Spec: S1, S3, S5.
- **T5** ✅ Sitio y docs: `build_site.py` (labels/orden), `README.md`, `REPORT.md`, tests de sitio. Route: inline (parent). Commit de integración. Spec: S3, S6.
- **T6** ✅ Corrida real + verificación final: 363 crudos/normalizados → 245 únicos; 87 clusters; 360/363 venues resueltos; sitio 225 filas y 0 tripletas duplicadas; suite 369 tests. Route: inline (parent). Spec: S6.

## Log

- **L1** (request original, verbatim): "1. Partí de feat/fuentes-ola-1 (o de main si primero mergeás la ola 1), así no perdés los cuatro collectors nuevos.
2. Leé odd/tasks/fuentes-ola-1.md para el contexto y el formato de trabajo.
3. Candidatos de la ola 2: Teatro Auditorium (teatroauditorium.gba.gob.ar), Teatro Colón (mardelplata.gob.ar/colonprogramacion) y TuEntrada.
4. Plateanet queda para la ola 3, con estrategia manual o acuerdo: está detrás de Incapsula/hCaptcha."
- **L2**: Baseline verificado 2026-10-23: 253 tests passed; rama `feat/fuentes-ola-2` creada desde `feat/fuentes-ola-1` (commit `5393f4e`).
- **L3** (investigación): Auditorium es Drupal 10; `/programacion?page=0..6` devuelve 37 actividades (6 por página) y cada ficha tiene JSON-LD Event. Las salas son Roberto J. Payró, Astor Piazzolla, Gregorio Nachman, Jorge Laureti - Puerto, Café Teatral Emilio Alfaro y Foyer; los horarios vienen como pares inicio/fin en `<time datetime>`. El detalle no trae precios: solo "Localidades en venta por Plateanet" o "Entrada libre y gratuita".
- **L4** (investigación): Teatro Colón es Drupal 7 y renderiza la programación mensual como HTML plano en dos columnas `div.well.span5`; encabezado de mes (OCTUBRE) y líneas "Jueves 1 a las 20:30 hs" + título + descripción + precios. 27 eventos en la página de octubre; un evento gratis.
- **L5** (investigación): TuEntrada es Next.js. `GET /busqueda?q=mar%20del%20plata` renderiza del lado del servidor una tarjeta (título, fecha DD-MM-YYYY, hora, venue+ciudad, slug, imagen). La ficha incrusta `eventSessions` en el payload RSC con fechas ISO, venue, ciudad y estado; el API `access.tuentrada.com` exige auth. Hoy hay 1 evento MDP: PAREN LA MANO en el Polideportivo (el mapa de la ficha lo identifica como Estadio Polideportivo Islas Malvinas). `teatro-enrique-carreras` no tiene eventos.
- **L6**: Writers paralelos completaron T1-T3 con RED → GREEN observado (auditorium 32 tests, colon 44, tuentrada 32). Corrección del parent sobre dos defectos reales: la línea "Viernes 16 a las 19 y 21:30 hs" de Colón ahora genera su propio evento (28 en vez de 27, seller Fever) y el fallback de rango de TuEntrada ya no inventa fechas (`occurrences=[]`, `recurrence_unknown=True`).
- **L7**: RDD activo (global on). `gentle-ai review assess --base-ref 5393f4e --committed-only --json` devolvió `review_due: high_risk` pero el runtime `opencode v0.0.0-wider-session-202610222350` no es elegible para transporte inmutable: `immutable_review_transport_unsupported`, `next_action=stop`, `retry_safe=false`, `mutation_outcome=not_started`. Se preserva el resultado tipado y se sigue con las verificaciones ordinarias; no se desactiva RDD (decisión del usuario).
- **L8**: La primera corrida real (363 eventos, 228 únicos) mostró 7 clusters falsos del festival de cine del Auditorium (mismo venue/fecha, prefijo "41° Festival Internacional de Cine:") y un par de Venti con títulos casi iguales. Se corrigió `lib/dedupe.py`: el fuzzy entre eventos de la misma fuente ya no une; dentro de una fuente solo une slug de ticketera o título normalizado exacto. Tests nuevos en `tests/test_dedupe.py`; se relanzó la corrida.
- **L9**: Corrida final 2026-10-23T03:37Z: 363 crudos → 363 normalizados → 245 únicos; 87 clusters (205 involucrados, 118 reducciones); 0 clusters same-source; venues 360/363; duración 334 s. Sitio con `--today 2026-10-23`: 225 filas próximas, 36 del finde, 42 venues, 0 tripletas duplicadas. Suite: 369 tests en verde.
