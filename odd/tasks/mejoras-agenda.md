# Mejoras de agenda (7 puntos)

Cierra la deuda detectada al auditar el sitio: links rotos, filtros y saneamiento de datos. Cada tarea se verifica sola; la suite debe quedar en verde salvo la falla previa conocida `test_build_site.py::test_known_ticket_url_is_linked`, que depende del calendario y no es parte de este trabajo.

## Specs

**S1.** Mapear en `lib/sellers.py` los 6 hosts que ya aparecen en los datos y no están: `feverup.com` → Fever, `edenentradas.ar` → Eden Entradas, `centralticket.net` → Central Ticket, `events.flashpass.com.ar` → Flashpass, `wearebombo.app.link` → Bombo (deep link), `ccave.fanz.com.ar` → Chauvin (tenant Fanz). Los eventos con esos links deben salir con `seller` y CTA de compra; hoy son 22 filas sin vendedor.

**S2.** `https://www.mardelplata.gob.ar/colonprogramacion` contiene los 11 eventos de Colón y no pagina por fecha: debe valer como link de Fuente mediante excepción explícita en `is_event_page`, recuperando 7 filas hoy sin link (2 sólo Colón + 5 compartidas con Municipal).

**S3.** Toggle «solo con entrada online» en el sitio: aísla los eventos con `ticket_url` (235 de 324) sin ocultar fuentes ni agenda cultural. Debe convivir con los filtros y contadores existentes, y recordar la elección como el tema.

**S4.** Descartar los eventos fuera de un horizonte de ±12 meses: hoy entra `2029-01-29` («Recital de Violín y Piano», municipal). El descarte va en `build_site.py`, no en el pipeline, para no perder el dato crudo.

**S5.** Aplicar `display_title` a Municipal y Colón: títulos como «CICLO ANUAL BALLET DE CÁMARA DE LA ESCUELA MUNICIPAL» deben mostrarse legibles, conservando el título crudo en los datos.

**S6.** Capturar el sitio de la sala desde el panel municipal (el `<a>` externo del panel, ej. `www.centrodeartemdp.com`) y usarlo como link de Fuente cuando no hay ficha del evento: son 20 filas hoy sin link.

**S7.** Deuda de venues/dedupe: resolver los 90 venues sin resolver que sean venues reales (no productoras, no typos) y corregir sólo duplicados probados en los 16 buckets venue+fecha con más de una fila. No unir eventos distintos: los 5 pares municipal↔Colón son el mismo evento; las dos funciones del mismo día en Club TRI no lo son.

## Tasks

| ID | Spec | Alcance | Commit |
|---|---|---|---|
| T1 | S1 | 6 hosts de ticketera en el mapa de vendedores | `e609ff1` |
| T2 | S2 | Colón como fuente enlazable | `56a40d5` |
| T3 | S3 | Toggle «solo con entrada online» | `56a40d5` |
| T4 | S4 | Horizonte de ±12 meses | `56a40d5` |
| T5 | S5 | Títulos legibles en Municipal/Colón | `56a40d5` |
| T6 | S6 | Sitio de la sala desde el panel municipal | `56a40d5` |
| T7a | S7 | Venues sin resolver (587/601) y 6 duplicados probados | `8028d59` |
| T7b | S7 | Join cross-source de título de un token contra cartel completo | `5f45880` |
| T8 | — | Defectos de la verificación independiente (link duplicado, campo muerto, gate de esquema, doc) | `c7f5f47` |

T2 a T6 comparten commit porque los tres writers trabajaron sobre el mismo `build_site.py` en un solo árbol: separarlos exigía staging por hunks. Slice resultante: 1.326 líneas sobre `feat/mejoras-agenda` en 6 commits, por encima de la guía de ~400 por slice; el límite se registra acá y la forma de entrega (un PR o slices encadenados) se decide al publicar.

## Log

**L4.** Verificación final (2026-11-21): suite **689 pasan, 1 falla** (la previa dependiente del calendario, `test_known_ticket_url_is_linked`). Build `--today 2026-11-21`: 285 filas, 216 con entrada online, 7 links a `colonprogramacion`, ningún título con 2029. En navegador: el chip «Solo con entrada online 216» filtra 44 → 33 filas del finde, deja 0 filas sin entrada visibles, `aria-pressed="true"` y el contador acompañando.

**L5.** Deuda declarada que no se tocó: 14 filas siguen sin venue resuelto (productoras, zonas, ruta suelta, artista en el campo de sala); 8 duplicados probados quedaron sin unir, cada uno con su blocker escrito en el handoff de T7.

**L6.** Verificación independiente (`gentle-ai-verify`) sobre el branch: S1, S2, S3 (navegador real), S4, S5 y S7 en PASS; S6 marcado FAIL por discrepancia entre el texto del spec («usarlo como link de Fuente») y la forma aprobada (línea propia `Sala:`). Se mantiene la forma aprobada: el sitio de la sala no debe disfrazarse de procedencia. La verificación también detectó cuatro defectos, corregidos en `c7f5f47`: link de Fuente duplicando el CTA en 119 filas, campo `has_ticket` muerto en el payload, `is_event_page` aceptando `ftp://` y raíz con query, y números desactualizados en `docs/fuentes.md`. Suite tras el fix: **692 pasan, 1 falla** (la previa).

**L7.** Deuda que sólo se cierra con una corrida real del pipeline: `venue_url` no existe en el snapshot, y los 6 merges de dedupe no se ven en el sitio porque `data/events_deduped.json` es salida del pipeline. Se lanzó `run_pipeline.py` para materializarlos.



**L1.** «arregla todo. Los 7 puntos»

**L2.** Alcance aprobado, definido en el mensaje anterior: 1) mapear los 6 hosts; 2) recuperar los links de Colón; 3) filtro «solo con entrada online»; 4) sanear fechas imposibles; 5) `display_title` para municipal y colón; 6) capturar el sitio de la sala; 7) deuda de dedupe y venues.

**L3.** Restricciones del usuario que estas tareas deben respetar: «Necesito que nos aporte el link directamente del evento o de la compra de la entrada si es que tiene»; «los links se note mas que es un link»; «Lo que me hace ruido es poner eventos que no tengan link de compra y no tengan link de donde se anuncia»; «Los que mas me interesarian dejar son los municipales».
