# Deuda de agenda: duplicados, venues y hallazgos del review

Cierra lo que quedó fuera de `mejoras-agenda` (su L5) y los seis hallazgos no bloqueantes del review nativo del rango `main..2d006f7`.
Rama: `feat/deuda-agenda`, desde `origin/main` (`41de1e9`). Runner: `.venv/bin/python -m pytest tests/ -q`.

## Specs

**S1.** Cerrar los 8 buckets duplicados que T7 dejó sin unir, cada uno con veredicto explícito —unido o descartado con la razón probada—. Hoy no hay ninguno sin decisión:

| Bucket | Tema |
|---|---|
| `abbey-road` 2026-12-05 | Municipal «Retropartuza Fest» contra el título concatenado de Articket |
| `brew-house` 2026-11-27 | «NOCHE RASTONE» contra «¡FIESTA EN MAR DEL RASTONE!» |
| `sheraton-mar-del-plata` 2026-12-05 | Dos ediciones Vinmusic distintas (Sparkling vs Cheers), no una noche repetida |
| `stadium-la-normandina` 2026-11-21 | «Fiesta La Nosti» contra «La Nosti - 5 aniversario» (sin blocker escrito) |
| `teatro-auditorium` 2026-12-05 | Par Valentín Garvie bloqueado por `series_prefix_conflict` |
| `el-argentino-bar` 2026-11-20 | Mismo evento dos veces, una sola fuente |
| `la-carpa` 2026-12-24 | Mismo evento dos veces, una sola fuente |
| `umano` 2027-01-08 | Venti contra Qué Hacemos; `08 .01.2027` no matchea `_DATE_TOKEN_RE` |

**S2.** Resolver los venues que quedan sin resolver en el snapshot vigente. El número de L5 («14 filas») quedó desactualizado: `data/events_normalized.json` tiene hoy **15 filas** con `venue_name` no resuelto y `data/last_run.json` reporta `"resolved": 572, "unknown": 23` sobre 595. Resolver las que sean venues reales y dejar explícito, con criterio escrito, por qué las demás no lo son: `Playa Chapadmalal`, `Playa Grande` y `Mar Del Plata` son zonas o ciudad; `El Plan de la Mariposa` es el artista; `Avenida Patricio Peralta Ramos` y `, Ruta Provincial 11` son vías sueltas; `Antesala`, `Festival Silvermare` y las filas vacías necesitan decisión caso por caso.

**S3.** Cerrar los cuatro follow-ups del review, cada uno con un test que falle antes del fix:

- **S3a.** `lib/dedupe.py:474`: el join por slug une todos los anchors compatibles pero `pairs` anota sólo `anchors[-1]`. La evidencia debe reportar el merge completo y dejar de depender del orden de entrada.
- **S3b.** `verify/duplicates.py:45-53`: `_dates_compatible` reimplementa la regla de `lib/dedupe._slug_dates_compatible` y además agrega un fallback de `date_start`, así que no es idéntica a ninguna de las dos helpers de `lib`. Debe existir una sola regla, con paridad probada.
- **S3c.** `build_site.py:276`: `"/obtener_eventos/"` exige barra final, así que `https://articket.com.ar/obtener_eventos?cantidad_eventos=500` se acepta como página de evento y puede publicarse como Fuente.
- **S3d.** `site_assets/app.js:135`: `var Filter = window.CarteleraFilter;` se desreferencia sin fallback; si el módulo no carga, `matches()` e `inView()` tiran y se cae todo el filtrado del cliente, incluido el toggle de entrada.

**S4.** Versionar la deuda que hoy sólo existe fuera del repo: el handoff de T7 con los ocho blockers no está en ningún archivo, y el cierre del review anterior tampoco (L13 quedó sin commitear). Ambos quedan registrados en este documento y en `odd/tasks/mejoras-agenda.md`.

**S5.** Dejar el árbol local coherente con `origin/main`: sincronizar el worktree, commitear el registro pendiente y eliminar las ramas locales redundantes (`chore/data-refresh`, `feat/mejoras-agenda`) una vez que su contenido ya está en `main`.

## Tasks

| ID | Spec | Alcance | Commit |
|---|---|---|---|
| T1 | S4 | Documento de feature, handoff de T7 versionado y L13 | `4484be5` |
| T2 | S1 | Ocho buckets con veredicto y tests de unión | `4619338` |
| T3 | S2 | Quince filas de venue y criterio escrito | `789f656` |
| T4 | S3a | Evidencia de pares en el join por slug | `aa8ac31` |
| T5 | S3b | Una sola regla de compatibilidad de fechas | `b837351` |
| T6 | S3c | Guard de Articket sin barra final | `20f04aa` |
| T7 | S3d | Fallback de `CarteleraFilter` en el cliente | `a3ef4aa` |
| T8 | S5 | Sincronización y limpieza de ramas | — |

T4 a T7 son independientes entre sí y tocan archivos disjuntos salvo `tests/`, que se reparte por suite: `tests/test_dedupe.py`, `tests/test_verify.py`, `tests/test_build_site.py` y un test nuevo para `app.js`.

T1 a T7 suman 1.561 líneas autoradas en 7 commits, muy por encima de la guía de ~400 por slice; el límite se registra acá y la forma de entrega (un PR o slices encadenados) se decide al publicar.

**L5.** T3 (2026-11-24): venues. Nueva API `lib/venues.resolve_event(title=, venue_name=, venue_raw=)`: los campos de venue ganan y sólo si no hay ninguno se usa la mención final del título (`en`/`at`/`@`) contra un alias **ya registrado**; nunca se inventa una sala. Siete entradas nuevas (`samsara-beach`, `immc`, `the-clap`, `fisker`, `lina-club-cultural`, `fichin-bar`, `club-de-foodies`) y el alias «Casino Central de Mar del Plata» en `casinos-de-la-provincia`.

Cableado en `run_pipeline._venue_stats` (`run_pipeline.py:120-131`): sin caller, el resolver era código muerto y el snapshot no cambiaba — el mismo defecto que el review anterior marcó con `has_ticket`. Diferencial sobre 595 filas: **23 unknown → 12**, 11 flips (3 por título + 8 por registro + el alias), 0 regresiones y ningún venue re-apuntado a otro id. `resolve()` y `venue_key()` siguen byte-idénticas (chequeo AST). RED 9 fallas / GREEN 50 en `tests/test_venues.py`; suite completa 778 pasan, 1 falla previa.

Quedan 12 filas sin resolver, con criterio escrito en los tests: `Playa Chapadmalal` y `Playa Grande` son zonas, `Mar Del Plata` es la ciudad, `Avenida Patricio Peralta Ramos` y las rutas son vías sin sala, `Antesala` es la productora de Bombo, `Festival Silvermare` es marca de festival, `El Plan de La Mariposa` es el artista, y las filas de Bresh y Camelphat no nombran sala en título, campos ni dirección.

**L6.** T4 (2026-11-24): evidencia de pares. En `lib/dedupe.py:555-575` el borde de slug ahora registra un par `ticket_slug` por **cada** anchor compatible que une (antes sólo `anchors[-1]`), con las dos referencias ordenadas para que el registro no dependa del orden de entrada. `union()` sigue recibiendo la misma secuencia, así que el membership no cambia por construcción: 123 clusters antes y después, sets idénticos. Pares 555 → 618 (438 → 439 distintos); el único borde nuevo es `punto:19994 ↔ elevenflow:tan-bionica-…`, exactamente la evidencia que el defecto ocultaba. RED 2 fallas / GREEN 83. Riesgo declarado: los registros redundantes suben de 117 a 179 (duplicación pre-existente al cruzar el pase de venue); deduplicarlos toca todos los tipos de par y queda como follow-up.

**L7.** T5 (2026-11-24): una sola regla de fechas. `verify/duplicates.py:71` llama `dedupe._slug_dates_compatible` en lugar de tener su propia copia; el fallback de `date_start` sobrevive como paso explícito (`_with_known_dates`) que además reusa `dedupe.occurrences_of`. Tabla de paridad de 10 casos, incluida una prueba de «flip»: si se invierte la regla de `lib`, el verificador la sigue. El verificador queda **más estricto** en 2 casos (una fila con sólo `date_start` contradice la noche conocida), nunca más laxo. RED 10 fallas / GREEN 45. Riesgo: `_slug_dates_compatible` es privada; un rename futuro falla fuerte con ImportError, que es la señal buscada.

**L8.** T6 (2026-11-24): guard de Articket. `LISTING_URL_PATTERNS` pierde la barra final y `is_event_page` compara contra `_LISTING_MARKERS`, la misma tupla con la barra recortada, así que el endpoint se rechaza con y sin barra, con query y con fragmento; la normalización cubre cualquier entrada futura. Diferencial: 605 URLs del snapshot, **0 flips**; build completo byte-idéntico. RED 3 fallas nuevas / GREEN 174 pasan y la previa conocida. Nota: `cultutickets.com/obtener_eventos` también pasa a rechazarse por compartir el marcador; no hay ninguna URL así en el snapshot.

**L9.** T7 (2026-11-24): el cliente ya no depende duro de `filter.js`. `app.js:133-149` sondea `filterReady`; sin módulo, `matches()` e `inView()` devuelven `true`, así que el render no tira y la página degrada a «sin filtrado del cliente» sin copiar ninguna regla. Los tests **ejecutan** `app.js` bajo Node con un stub de DOM, con y sin el módulo, y afirman estado renderizado: sin módulo, 3 filas visibles, contador «3 eventos», badges «3», sin error de init; con módulo, el toggle sigue recortando a 1. RED 3 fallas / GREEN 17.

**L10.** Corrección post-review (2026-11-24), después del intento `review-63730b341d30220e`, que escaló sin recibo por causalidad desconocida en R3-002:

- **R4-002 (defecto real, mío).** `_venue_stats` contaba como resuelto un venue inferido del título sin escribirlo en el evento: el reporte decía 559 resueltos mientras el snapshot seguía sin sala en esas filas. Ahora `run_pipeline._materialise_venues()` escribe el nombre del registro en el evento antes de `cluster_events`, y el contador lee sólo los campos del evento. Diferencial: 3 filas ganan `Mute Club de Mar`; 556/569 por campo → 559/569 tras materializar, igual al conteo de la regla completa. Efecto declarado: dos clusters existentes ganan un miembro, porque la puerta de venue del dedupe ahora ve la sala de esas filas.
- **R3-003.** El guard `series_prefix_conflict` vuelve a la versión base (sin `_SERIES_MARKERS`): un prefijo compartido sin marcador no es evidencia por sí solo. Consecuencia: el bucket `teatro-auditorium` vuelve a **rechazado**; el diferencial muestra 116 → 115 clusters y sólo ese bucket cambia.
- **R2-002.** El docstring de `_concatenated_title_match` declara que la regla es simétrica.

RED 5 fallas / GREEN 136 en `tests/test_dedupe.py` + `tests/test_venues.py`.

## Log

**L1.** «dale vamos con todo»

**L2.** Alcance aceptado, definido en la respuesta anterior: los 8 duplicados probados, los venues sin resolver, los hallazgos no bloqueantes del review y la limpieza de proceso (L13, worktree y ramas). Orden propuesto y aceptado: duplicados, después venues, después hallazgos.

**L3.** Mapeo del 2026-11-24 con evidencia `path:line`:

- **El handoff de T7 no está versionado.** Ningún archivo de `odd/`, `docs/`, `verify/` ni ningún `*handoff*` lo contiene; `odd/tasks/mejoras-agenda.md:50` (L5) es la única referencia. Los ocho blockers sobreviven sólo en el log de sesión `~/.gentle-shell/agent/gentle-agents/sessions/2026-11-21T14-18-22-363Z_01a1fe78-f51a-7152-a985-32638f48632a.jsonl:108`, sección «Proven duplicates left unfixed, with the exact blocker (report-only)». El bucket `stadium-la-normandina` directamente no tenía blocker escrito.
- **Los números de L5 están stale.** Son 15 filas sin venue (no 14) y `last_run.json:80-81` reporta 23 unknown sobre 595 filas.
- **Superficie de test actual.** `tests/test_dedupe.py:585` cubre el join por slug pero ningún test afirma cuántos pares se registran ni cuál anchor queda; no hay test de paridad entre `verify/duplicates.py` y `lib/dedupe.py`; `tests/test_build_site.py:924` cubre sólo la variante con barra de Articket; `app.js` no se ejecuta en ningún test, sólo se afirman strings y orden de carga.

**L4.** T2 (2026-11-24): **6 buckets unidos, 2 rechazados**.

| Bucket | Veredicto | Razón probada | Test |
|---|---|---|---|
| `abbey-road` | unido | Municipal «Retropartuza Fest» contra `RETROPARTUZAFEST - CHARLY MORENO`; los tokens pegados del municipal son el primer token de Articket. `_concatenated_title_match` (`lib/dedupe.py:253`). | `test_municipal_festival_joins_the_concatenated_articket_title` |
| `brew-house` | unido | «NOCHE RASTONE» contra «¡FIESTA EN MAR DEL RASTONE!», misma sala, fecha y 20:00. `_wrapper_title_match` (`:229`). La función de 23:30 queda fuera. | `test_party_wrapper_title_joins_noche_rastone` + near-miss |
| `sheraton-mar-del-plata` | **rechazado** | No es una noche repetida: son dos ediciones Venti con páginas de venta distintas (`vinmusic-mdq-sparkling-ii` codigo 20628 vs `vinmusic-mdq-aniversario-ii` codigo 20331). El join era falso positivo del prefijo `VINMUSIC MDQ`; `mdq` pasa a `_TITLE_STOPWORDS` (`:145`). | `test_two_vinmusic_editions_keep_their_own_rows` |
| `stadium-la-normandina` | unido | «Fiesta La Nosti» contra «La Nosti - 5 aniversario», misma sala y fecha. | `test_municipal_fiesta_la_nosti_joins_the_anniversary_title` |
| `teatro-auditorium` | **rechazado** | «Valentín Garvie Quinteto» contra «VALENTIN GARVIE QUINTETO FEAT HERNAN HECHT»: el prefijo compartido es el artista, pero el guard no puede distinguirlo de una serie sin marcador y abrir esa clase permitía unir entradas distintas. Ver L10. | `test_shared_artist_prefix_alone_does_not_join_two_descriptions` |
| `el-argentino-bar` | **rechazado** | Mismo show de Cual Pinta dos veces (89.4 de similitud) pero sólo el gate same-source los separa; relajarlo uniría funciones distintas. Regla intacta. | `test_same_source_fuzzy_duplicate_stays_split_by_design` |
| `la-carpa` | unido | La edición XMAS duplicada; el prefijo día+fecha sólo aceptaba `-`, así que el día de semana sobrevivía como token. `_TITLE_DATE_PREFIX_RE` acepta `.` y `/` (`:47`); el gate same-source no cambió. | `test_xmas_sinergia_rows_join_once_the_weekday_prefix_is_noise` |
| `umano` | unido | `08 .01.2027` con espacio antes del punto no matcheaba `_DATE_TOKEN_RE` (`:98`). | `test_date_stamp_with_a_space_joins_the_lineup_title` |

RED: 9 fallas, 72 pasan sobre el árbol base. GREEN: `tests/test_dedupe.py` 81 pasan. Diff: `lib/dedupe.py` +98/−13, `tests/test_dedupe.py` +328.

Riesgos declarados por T2: el guard `series_prefix_conflict` quedó más angosto, así que cualquier par «mismo arranque + cola distinta» en una sala y fecha ahora une por `title_prefix` (no hay tal par en ninguno de los dos snapshots); `mdq` entra global a los stopwords; y `data/events_deduped.json` queda stale hasta la próxima corrida del pipeline.
