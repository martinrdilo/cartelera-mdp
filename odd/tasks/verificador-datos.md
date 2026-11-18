# Verificador de datos: precio, fecha, link y duplicados

Objetivo: suite de verificacion offline + capa online opt-in que audite la fidelidad de precio/fecha/link contra el payload de origen y detecte duplicados no clusterizados; luego convertible en herramienta (`python -m verify`).
Rama: `feat/verificador-datos`. Estrategia de entrega: `single-pr` (una PR, commits por unidad).
Runner: `.venv/bin/python -m pytest tests/ -q`.

## Specs

S1. `python -m verify` sin argumentos corre la suite offline (snapshot + rebuild si hay `data/raw/` + duplicados) y sale 0 sin hallazgos `error`, 1 con al menos uno, 2 ante fallo interno. `--strict` promueve `warning` a falla. `--json` emite `{"version":1,"generated_at":...,"summary":{"errors":n,"warnings":n,"findings":n},"findings":[{"check","severity","message","evidence"}]}`.

S2. Snapshot de esquema e identidad: los 20 campos de `Event` presentes y con tipo correcto; `source` dentro de las fuentes conocidas (16: 13 modulos con `SOURCE` + `articket`/`cultutickets` + `chauvin`); fechas `YYYY-MM-DD` parseables; `time` `HH:MM`; `collected_at` ISO-8601; `(source, source_event_id)` unico.

S3. Integridad de ocurrencias: sin duplicados, ordenadas; `occurrences` no vacio exige `date_start` presente y contenido; toda ocurrencia dentro de `[date_start, date_end]` cuando `date_end` existe; `occurrences` vacio solo con `recurrence_unknown` o `multi_date_incomplete`.

S4. Integridad de precio: `price_min >= 0`; `is_free is True` exige `price_min in (None, 0)`; `is_free is False` exige `price_min is None or price_min > 0`; `price_min` presente exige `currency` presente.

S5. Integridad de link: `ticket_url` y `raw_url` con esquema `http(s)`; si hay `seller` y `ticket_url`, el host debe resolver al mismo seller segun `lib.sellers` (host desconocido = warning, no error).

S6. Estructura de dedupe: `total_normalized`, `unique_events` y `events_in_clusters` iguales a los recomputados; todo cluster con >= 2 miembros; cada miembro existe en el snapshot exactamente una vez; ningun evento en dos clusters; toda evidencia de `pairs` referencia miembros del cluster.

S7. Coherencia del merge multi-fuente: reproducir la seleccion del sitio (`build_site.pick_field` / `SOURCE_ORDER`) y marcar warning cuando el precio mostrado pertenece a un seller distinto del seller del link mostrado, y cuando miembros de un cluster discrepan en `is_free`.

S8. Busqueda de duplicados no detectados: mismo slug de ticket (`lib.dedupe.extract_slug`) en clusters distintos = error; mismo `venue_key` + fecha compartida + `title_similarity >= 85` entre fuentes distintas en clusters distintos = warning, salteando pares que el guard de series (`series_prefix_conflict`) marca como entradas distintas. Sin pares repetidos.

S9. Rebuild desde el payload crudo: con `data/raw/*.json` presente, re-ejecutar `normalize` por modulo (sin la fase de enriquecimiento, que es de red) y comparar por `(source, source_event_id)` los campos auditados distintos de `collected_at`; reportar faltantes, sobrantes y cambios. Los campos derivados de red en Articket multi-fecha (`occurrences`, `date_end`, `multi_date_incomplete`) se eximen por evento. Los cambios de fecha que son exactamente +-1 año se reportan como `rebuild.time_dependent`. Sin `data/raw/`, emitir `info` y seguir.

S10. `links` (online, opt-in): pedir cada `ticket_url`/`raw_url` unico, reportar HTTP >= 400, fallos de red, esquema invalido y redireccion a otra ruta/host como warning.

S11. `live --source NAME` (online, opt-in, fuente obligatoria): colectar y normalizar esa fuente ahora y comparar contra el snapshot con la misma comparacion de S9.

S12. Tests offline en `tests/test_verify.py` que cubren S1-S9; smoke test sobre el snapshot real que exige reporte bien formado y exit en `{0,1}`.

S13. README con comandos, codigos de salida y alcance de cada capa; documento de tarea con evidencia.

## Tasks

- T1 — Paquete `verify/`: `core` (Finding/Report/exit codes), `cli` y `__main__`. `S1`. Route: inline. ✅
- T2 — `snapshot` de esquema, ocurrencias, precio y link. `S2-S5`. Route: inline. ✅
- T3 — Invariantes de dedupe y coherencia de merge. `S6-S7`. Route: inline. ✅
- T4 — Candidatos a duplicado. `S8`. Route: inline. ✅
- T5 — `rebuild` desde `data/raw/`. `S9`. Route: inline. ✅
- T6 — `links` y `live`. `S10-S11`. Route: inline. ✅
- T7 — Tests y README. `S12-S13`. Route: inline. ✅

## Log

L1 (pedido original, textual):
> de que manera podríamos agregar un verificador, o verificar que información del precio, del dia y del link de compra son correctas? Se podrán ejecutar casos de prueba en toda la aplicación, contrastando con la fuente original de la información para ver si es correcta. Se puede verificar tambien si hay duplicados?
>
> Preparemos una suite de pruebas para verificar esto y que luego se pueda convertir en una herramienta.

L2 — Decisiones de diseño: tres capas separadas (fidelidad interna offline, contraste con la fuente opt-in, duplicados). El contraste online se resuelve re-colectando la fuente en vez de escribir un segundo parser; los precios que cambian se reportan como drift, no como falla de CI. `rebuild` es offline porque `data/raw/` ya contiene el payload exacto de la corrida.

L3 — Evidencia: `tests/test_verify.py` 21 casos; suite completa 590 passed. `python -m verify` sobre el snapshot real: 626 eventos, 141 clusters, 1 error, 33 warnings, 1 info. Commit de código: `3454873`.

L4 — Hallazgos reales en la primera corrida: `clubtri:718` con título vacío (error); `municipal:49411` ("An Espil") y `quehacemos:57512` ("AnEspil") son el mismo show y el dedupe los dejó separados; el mapa `lib/sellers.py` no conoce `ticketmas.ar` ni `chauvin.com.ar` (14 warnings); dos clusters mezclan fuentes gratis y pagas.

L5 — Correcciones al verificador tras la primera corrida: las fechas relativas re-parseadas contra hoy se clasifican como `rebuild.time_dependent` (warning); `date_end` de Articket multi-fecha se exime por ser derivado de red; los candidatos a duplicado se restringen a fuentes distintas y umbral 85, con el guard de series de `lib/dedupe` (renombrado a público `series_prefix_conflict`); el nombre de vendedor se normaliza (`Venti.live` ≡ `Venti`). Se revirtió una ampliación de `lib/sellers.py` porque invalidaba 17 filas del snapshot sin pedido de re-corrida.

