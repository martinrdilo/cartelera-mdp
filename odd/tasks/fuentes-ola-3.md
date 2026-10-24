# Fuentes ola 3 — Cual Pinta, Eleven Flow y Passline

Objective: ampliar la cobertura de eventos de Mar del Plata sumando tres fuentes (Cual Pinta, Eleven Flow y Passline), sin duplicar eventos en el sitio y sin agregar un collector directo de Plateanet, que sigue bloqueado por Incapsula.
Branch: `feat/fuentes-ola-3` (parte de `main` @ `0b79f54`). Delivery: work-unit commits sobre la rama, sin PR (patrón de las olas 1-2). Test runner: `.venv/bin/python -m pytest tests/ -q`.

## Specs

- **S1**: Agregar al pipeline las fuentes de la ola 3: **Cual Pinta** (`cualpinta.com/mar-del-plata`), **Eleven Flow** (`elevenflow.app/recitales-en-mar-del-plata`) y **Passline** (`passline.com`). Cada fuente expone `collect() -> list[dict]` y `normalize(records) -> list[Event]`, como las fuentes existentes.
- **S2**: Evidencia relevada el 2026-10-23, que fija el alcance real de cada collector:
  - **Cual Pinta**: `robots.txt` permite y declara sitemap; `sitemap.xml` lista **144** URLs `/mar-del-plata/eventos/`, todas vigentes en la muestra. El listado `/proximos` topea en 30 y `?page=2` repite: la enumeración va por sitemap. La ficha trae JSON-LD `Event` (`name`, `startDate` con offset `-03:00`, `location.name` + `address`, `offers.price`/`priceCurrency`, `image`) y el **único link de venta externo** (Articket, Plateanet, sitio del venue). La categoría sale del `span.cp-chip` (Música, Recital, Fiesta, Teatro, Concierto clásico, Stand-up, Cine, Deportes, Gastronomía, Fiesta de disfraces).
  - **Eleven Flow**: página server-rendered con **53** recitales anunciados y 54 links de evento. Dos `ItemList` JSON-LD aportan 33 `MusicEvent`; el resto está en HTML. La ficha trae un `MusicEvent` JSON-LD completo y linkea al vendedor (observado: Plateanet). Es la única vía observada a eventos que solo vende Plateanet.
  - **Passline**: `/eventos` está detrás de Queue-it (bucle de redirects); **no se toca**. El descubrimiento es por lista curada de slugs de venue: `roomie-club`, `zwan`, `mr-jones`, `la-caseta`, `centro-cultural-victoria-ocampo-villa-victoria`. Página de venue → links `/eventos/<slug>`; ficha con fecha en español (`Viernes 30 de Octubre 2026 - 23:30 hrs`), venue + dirección y precio (`$20.000`). Hoy: **4 eventos MDP**.
- **S3**: "Dejemos afuera mi criterio sobre los revendedores y lo que te dije. Podríamos agregar las otras fuentes y tener más opciones de eventos?" Las tres fuentes participan del dedupe existente (venue canónico + intersección de `occurrences` + título normalizado) y el sitio no renderiza dos filas para el mismo evento. Actualizar `data/venues.json` con las salas/alias que aparezcan.
- **S4**: "Plateanet queda para la ola 3, con estrategia manual o acuerdo." No se agrega collector directo de Plateanet: home, fichas, `api.plateanet.com` y el host mobile devuelven el challenge de Incapsula. Su inventario entra solo por los links de Cual Pinta y Eleven Flow, y `seller` se deriva del host del link.
- **S5**: Solo lectura, user-agent `cartelera-mdp-pipeline/0.2 (local research)`, ~1 req/s. Los tests no pegan a la red: usan fixtures reales de `tests/fixtures/`. No se usa la API interna de Cual Pinta (`robots.txt` la prohíbe) ni se evade Queue-it.
- **S6**: No romper las fuentes existentes ni la suite: baseline **374 tests** en verde.
- **S7**: Actualizar `build_site.py` (etiquetas de fuente y prioridad de campos), `run_pipeline.py` (módulos), `README.md` y `REPORT.md`; cerrar con una corrida real y métricas observadas.

## Tasks

- **T0** TBD — `lib/sellers.py` compartido: mover el mapa host→vendedor de `collectors/punto.py` a un módulo reusable (sumando Passline) y hacer que Punto lo importe. Route: inline (parent). Spec: S1, S6.
- **T1** TBD — Cual Pinta collector: `collectors/cualpinta.py` + `tests/test_cualpinta.py` + fixtures. Enumeración por sitemap, ficha JSON-LD, categoría por chip, link de venta externo, precio y hora. Route: delegated (writer A). Spec: S1, S2, S4, S5.
- **T2** TBD — Eleven Flow collector: `collectors/elevenflow.py` + `tests/test_elevenflow.py` + fixtures. Listado server-rendered + `MusicEvent` de la ficha; descartar `endDate` inválido. Route: delegated (writer B). Spec: S1, S2, S5.
- **T3** TBD — Passline collector: `collectors/passline.py` + `tests/test_passline.py` + fixtures. Lista curada de venues, fechas en español, precio y dirección. Route: delegated (writer C). Spec: S1, S2, S4, S5.
- **T4** TBD — Integración: `data/venues.json` (alias de las tres fuentes), `run_pipeline.py`, `build_site.py` (labels/orden), tests de venues y aceptación. Route: inline (parent). Spec: S3, S7.
- **T5** TBD — Docs: `README.md`, `REPORT.md` (sección 8), `data/` snapshot. Route: inline (parent). Spec: S7.
- **T6** TBD — Corrida real + verificación final: métricas observadas, cero tripletas duplicadas, suite completa, verificador independiente si corresponde. Route: inline (parent). Spec: S7.

## Log

- **L1** (request original, verbatim): "Estábamos recién haciendo una serie de mejoras en esta aplicación. Terminamos la ola 2 y tendríamos que empezar la ola 3. ¿Puedes levantar el contexto y fijarte?"
- **L2** (cambio de criterio, verbatim): "Dejemos afuera mi criterio sobre los revendedores y lo que te dije. Podríamos agregar las otras fuentes y tener más opciones de eventos?"
- **L3**: Contexto levantado 2026-10-23: `main` local en `0b79f54` con las olas 1-2 mergeadas (fast-forward); `origin/main` en `896934c` (12 commits sin pushear). Árbol limpio. Suite 374 tests en verde. Snapshot del `2026-10-23T03:37Z`: 363 crudos → 245 únicos, 87 clusters, 0 same-source. RDD `on` (global); el runtime de la ola 2 no era elegible para transporte inmutable y se registró como limitación.
- **L4** (spike de fuentes): Plateanet sigue cerrado (home, `/obra/`, API y mobile devuelven ~850 B de Incapsula; solo `sitemap.txt` con 378 URLs sin ciudad/fecha). Medios locales (0223, El Marplatense, La Capital, Infobrisas, Qué Digital) publican prosa sin JSON-LD ni `<time>`: descartados. Bandsintown devuelve 403 (Cloudflare y API): no enumerable por ciudad. Cual Pinta, Eleven Flow y Passline quedaron como las tres únicas fuentes viables; el usuario aprobó sumarlas.
- **L5**: Cual Pinta: 144 eventos en sitemap, 0 pasados en una muestra de 24; categorías observadas Música 8, Recital 4, Fiesta 3, Teatro 3, Concierto clásico 1, Stand-up 1, Cine 1, Deportes 1, Gastronomía 1, Fiesta de disfraces 1. Decisión: incluir todas las categorías (el sitio ya publica teatro y cine) y no filtrar por categoría en esta ola.
- **L6**: Quirk de Eleven Flow: en el listado, `endDate` puede ser anterior a `startDate` (`20:00` → `00:00` del mismo día). El normalizador debe usar `endDate` solo si es estrictamente posterior a `startDate`; nunca inventar un rango multi-día.
