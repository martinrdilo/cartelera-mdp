# cartelera-mdp — pipeline de extracción

Pipeline local que extrae eventos musicales reales de Mar del Plata desde 3 fuentes (agenda municipal EMTUR, Articket/CultuTickets y Club TRI), los normaliza a un esquema común, expande los eventos multi-fecha y detecta duplicados entre fuentes usando un canónico de venues. Sirve para medir cobertura, calidad de datos y esfuerzo de dedupe antes de invertir en producto, y alimenta el sitio estático de la Fase 2 (`build_site.py`). Resultados: ver `REPORT.md`.

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

3. Correr el pipeline completo (fetch real, ~1 req/s, tarda ~30 segundos):

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

`site/` no se versiona: se regenera en cada corrida. El hero "Este finde" usa la ventana jueves–domingo (de lunes a miércoles, la del finde que viene); la lista completa filtra por fecha, lugar y gratis en el navegador, sin recargar.

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
| `lib/schema.py` | `Event`: esquema normalizado único (fuente, título, lugar, fechas ISO, `occurrences`, hora, precio, link de compra, etc.). |
| `lib/dates.py` | Parsing de `dd/mm/yyyy` y fechas en español sin año; extracción de hora. |
| `lib/occurrences.py` | Expansión multi-fecha: rangos municipal por día de semana y detalle Articket (select `fechas_evento` / JSON-LD). |
| `lib/venues.py` | Registry de venues: normalización y resolución por alias (`data/venues.json`). |
| `lib/dedupe.py` | Dedupe por venue canónico + intersección de `occurrences`, join por slug y fuzzy de títulos (umbral 85). |
| `run_pipeline.py` | Orquesta collect → normalize → enrich → dedupe y escribe `data/` (atómico; no pisa outputs si una fuente falla). |
| `scripts/daily.sh` | Corrida diaria con log; insumo para cron/systemd. |
| `build_site.py` | Genera el sitio estático en `site/`: merge de clusters, ventana jue–dom, tarjetas, SEO y assets. |
| `site_assets/` | Fuente del CSS, el JS (filtros, compartir, hooks) y el favicon; `build_site.py` los copia a `site/`. |
| `.github/workflows/deploy.yml` | Deploy diario del sitio a GitHub Pages (pipeline best-effort + build + Pages). |
| `tests/` | Pytest: venues, fechas, ocurrencias, municipal, dedupe, runner y sitio. |

Cada collector expone `collect() -> list[dict]` (crudo) y `normalize(records) -> list[Event]`. Si una fuente falla en la colecta, el runner no escribe los outputs y sale distinto de cero.

## Notas

- Solo lectura sobre sitios externos; UA `cartelera-mdp-pipeline/0.2 (local research)` y ~1 req/s.
- `.venv/`, `data/raw/` y `logs/` no se versionan; los JSON normalizados/dedupeados y `data/last_run.json` sí, como evidencia.
- Decisiones de tuning y limitaciones conocidas: ver `REPORT.md`.
