# cartelera-mdp — pipeline de extracción

Pipeline local que extrae eventos musicales reales de Mar del Plata desde 11 feeds (agenda municipal EMTUR, Articket, CultuTickets, Club TRI, Venti, Ticketek, Bombo, Punto Mar del Plata, Auditorium, Teatro Colón y TuEntrada), los normaliza a un esquema común, expande los eventos multi-fecha y detecta duplicados entre fuentes usando un canónico de venues. Sirve para medir cobertura, calidad de datos y esfuerzo de dedupe antes de invertir en producto, y alimenta el sitio estático de la Fase 2 (`build_site.py`). Resultados: ver `REPORT.md`.

## Camino rápido

1. Crear entorno e instalar dependencias:

   ```bash
   uv venv .venv
   uv pip install --python .venv/bin/python -r requirements.txt
   ```

2. Correr los tests de lógica pura (venues, fechas, ocurrencias, dedupe, runner y sitio):

   ```bash
   .venv/bin/python -m pytest tests/ -q
   ```

3. Correr el pipeline completo (fetch real, ~1 req/s; tarda varios minutos porque Punto y Auditorium enriquecen cada ficha con su detalle):

   ```bash
   .venv/bin/python run_pipeline.py
   ```

4. Revisar resultados: `data/events_normalized.json` (eventos con `occurrences`), `data/events_deduped.json` (clusters de duplicados con evidencia), `data/last_run.json` (resumen de la corrida) y `data/raw/<fuente>.json` (crudo por fuente).

## Corrida diaria

`scripts/daily.sh` corre el pipeline desde la raíz del repo y agrega la salida a `logs/daily.log` (crea `logs/` si falta). Sale con el código del pipeline: `0` si todo salió bien, distinto de `0` si alguna fuente falló. En un fallo parcial los outputs no se pisan: queda la evidencia en `data/raw/<fuente>.error.json`.

El schedule no se instala solo; ejemplos:

- cron, todos los días 08:00:

  ```cron
  0 8 * * * /home/martin/workspace/cartelera-mdp/scripts/daily.sh
  ```

- systemd de usuario: `~/.config/systemd/user/cartelera-mdp.service` con `Type=oneshot` y `ExecStart=/home/martin/workspace/cartelera-mdp/scripts/daily.sh`, más un `cartelera-mdp.timer` con `OnCalendar=daily` y `systemctl --user enable --now cartelera-mdp.timer`.

## Web local

El sitio estático (Fase 2) se genera desde los datos del pipeline, sin red y solo con la stdlib:

```bash
.venv/bin/python build_site.py                      # escribe site/ (index.html + assets/ + favicon.svg)
.venv/bin/python build_site.py --today 2026-10-14   # fecha fija, para probar ventanas y filtros
python -m http.server -d site                       # http://localhost:8000
```

La página es una agenda agrupada por fecha, no una grilla de tarjetas:

- **Temas claro y oscuro.** El botón del encabezado alterna el tema y recuerda la elección en `localStorage`; sin elección previa se respeta la preferencia del sistema. Los tokens de ambos temas viven en `site_assets/style.css`.
- **Navegación por día.** Las pestañas muestran "Finde" (jueves–domingo), cada día del finde con eventos y "Todo". Cada pestaña trae su cantidad y los contadores se recalculan al filtrar.
- **Filtros y búsqueda.** Chips de gratis y de las tres salas con más eventos, más búsqueda por banda, sala o dirección, todo en el navegador y sin recargar.
- **Detalle en la fila.** Cada evento expande sus fechas completas, la dirección con link a mapas, el origen de los datos y las acciones de compra y de compartir.
- **Flyers reales.** El destacado usa 4:5 y las miniaturas son cuadradas; si falta el flyer o falla la carga, se muestra una miniatura tipográfica con las iniciales.
- **Títulos legibles.** La ticketera suele mandar títulos en mayúsculas con la fecha pegada ("SANTO PECADO EN ABBEY ROAD 16-10"); el sitio muestra una versión legible y conserva el título crudo en los datos.


## Deploy

`.github/workflows/deploy.yml` publica el sitio en GitHub Pages:

- Se dispara con cada push a `main`, a mano (`workflow_dispatch`) y todos los días a las 08:00 de Mar del Plata (`0 11 * * *` en UTC).
- Corre el pipeline con `continue-on-error: true`: si una fuente falla, el build usa los datos ya versionados en `data/` y el sitio se publica igual.
- Genera `site/` con `build_site.py`, lo sube con `actions/upload-pages-artifact` y el job `deploy` lo publica con `actions/deploy-pages` en el environment `github-pages`.
- URL: <https://martinrdilo.github.io/cartelera-mdp/> — requiere Pages con source "GitHub Actions" en Settings → Pages (una sola vez).

## Estructura

| Archivo | Rol |
|---|---|
| `collectors/municipal.py` | Agenda EMTUR: HTML ISO-8859-1, `tipo` 11/16/19, paginado hasta página vacía (tope 15); segmenta cada rango con sus días de semana. |
| `collectors/muchticket.py` | Articket + CultuTickets: JSON `GET /obtener_eventos/?cantidad_eventos=500`, filtro Mar del Plata; enriquece multi-fecha desde la página de detalle. |
| `collectors/clubtri.py` | Home de clubtri.com = agenda; fechas "Mié 14 de Octubre" con inferencia de año. |
| `collectors/venti.py` | API JSON de Venti (Arena/La Vin/Quba/electrónica); filtra MDP por coordenadas del venue y convierte UTC a hora local. |
| `collectors/ticketek.py` | Búsqueda JSON de Ticketek + nodo CMS por show; fechas y precios desde `google_structured_data` (Bendu Arena, Tronador, Radio City). |
| `collectors/bombo.py` | Búsqueda JSON de Bombo + detalle JSON-LD para electrónica (Mute, The County); descarta pases y bundles. |
| `collectors/punto.py` | Agenda JSON de Punto Mar del Plata (`categoria=1`, música) + detalle JSON-LD para el link de venta. |
| `collectors/auditorium.py` | Agenda Drupal del Teatro Auditorium (`?page=N`, 6 actividades por página); fechas desde los pares `<time>` de cada tarjeta, salas mapeadas al venue canónico y detalle para vendedor/gratis. |
| `collectors/colon.py` | Programación mensual del Teatro Colón (Drupal 7, HTML plano en dos columnas); precios en es-AR, entrada libre y año inferido por ventana de 180 días. |
| `collectors/tuentrada.py` | Búsqueda server-rendered de TuEntrada filtrada a Mar del Plata; sesiones desde el payload RSC de la ficha, con fallback a la tarjeta. |
| `collectors/cualpinta.py` | Agenda de Cual Pinta: enumeración por `sitemap.xml` (144 fichas), JSON-LD `Event` en la ficha, categoría por chip y link de venta externo. |
| `collectors/elevenflow.py` | Agenda de Eleven Flow: listado server-rendered (53 shows) + `MusicEvent` JSON-LD en la ficha; descarta `endDate` anterior al inicio. |
| `collectors/passline.py` | Vendedor Passline: lista curada de venues MDP (Roomie, Zwan, Jones, La Caseta, Villa Victoria), fechas en español y precio es-AR desde la tabla de tickets. |
| `lib/schema.py` | `Event`: esquema normalizado único (fuente, título, lugar, fechas ISO, `occurrences`, hora, precio, link de compra, etc.). |
| `lib/dates.py` | Parsing de `dd/mm/yyyy` y fechas en español sin año; extracción de hora. |
| `lib/sellers.py` | Mapa host → vendedor compartido por los collectors que ven links de venta (Articket, Plateanet, Passline, etc.). |
| `lib/occurrences.py` | Expansión multi-fecha: rangos municipal por día de semana y detalle Articket (select `fechas_evento` / JSON-LD). |
| `lib/venues.py` | Registry de venues: normalización y resolución por alias (`data/venues.json`). |
| `lib/dedupe.py` | Dedupe por venue canónico + intersección de `occurrences`: slug, fuzzy de títulos, contención de tokens y prefijo de artista. |
| `run_pipeline.py` | Orquesta collect → normalize → enrich → dedupe y escribe `data/` (atómico; no pisa outputs si una fuente falla). |
| `scripts/daily.sh` | Corrida diaria con log; insumo para cron/systemd. |
| `build_site.py` | Genera el sitio estático en `site/`: merge de clusters, agenda por día, destacado, títulos legibles, SEO y assets. |
| `site_assets/` | Fuente del CSS (temas claro/oscuro), el JS (pestañas de día, filtros, búsqueda, detalle, compartir) y el favicon; `build_site.py` los copia a `site/`. |
| `.github/workflows/deploy.yml` | Deploy diario del sitio a GitHub Pages (pipeline best-effort + build + Pages). |
| `tests/` | Pytest: venues, fechas, ocurrencias, municipal, dedupe, runner y sitio. |

Cada collector expone `collect() -> list[dict]` (crudo) y `normalize(records) -> list[Event]`. Si una fuente falla en la colecta, el runner no escribe los outputs y sale distinto de cero.

## Notas

- Solo lectura sobre sitios externos; UA `cartelera-mdp-pipeline/0.2 (local research)` y ~1 req/s.
- `.venv/`, `data/raw/` y `logs/` no se versionan; los JSON normalizados/dedupeados y `data/last_run.json` sí, como evidencia.
- **Dedupe:** un cluster por venue canónico + intersección de fechas + slug o título (fuzzy, contención de tokens y prefijo de artista). El sitio aplica además un guard final: mismo venue + título normalizado + fecha compartida nunca se renderiza dos veces.
- **Fuentes de la ola 1:** Venti, Ticketek, Bombo y Punto MDP. **Ola 2:** Auditorium, Teatro Colón y TuEntrada. **Ola 3:** Cual Pinta, Eleven Flow y Passline. Plateanet sigue fuera de alcance directo (Incapsula/hCaptcha): su inventario entra solo por los links de Cual Pinta y Eleven Flow.
- Decisiones de tuning y limitaciones conocidas: ver `REPORT.md`.
