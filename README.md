# cartelera-mdp — spike de extracción

Spike local que extrae eventos musicales reales de Mar del Plata desde 3 fuentes (agenda municipal EMTUR, Articket/CultuTickets y Club TRI), los normaliza a un esquema común y detecta duplicados entre fuentes. Sirve para medir cobertura, calidad de datos y esfuerzo de dedupe antes de invertir en producto. Resultados: ver `REPORT.md`.

## Camino rápido

1. Crear entorno e instalar dependencias:

   ```bash
   uv venv .venv
   uv pip install --python .venv/bin/python -r requirements.txt
   ```

2. Correr los tests de lógica pura (fechas y dedupe):

   ```bash
   .venv/bin/python -m pytest tests/ -q
   ```

3. Correr el pipeline completo (fetch real, ~1 req/s, tarda ~30 segundos):

   ```bash
   .venv/bin/python run_spike.py
   ```

4. Revisar resultados: `data/events_normalized.json` (eventos normalizados), `data/events_deduped.json` (clusters de duplicados con evidencia) y `data/raw/<fuente>.json` (crudo por fuente).

## Estructura

| Archivo | Rol |
|---|---|
| `collectors/municipal.py` | Agenda EMTUR: HTML ISO-8859-1, `tipo` 11/16/19, paginado hasta página vacía (tope 15). |
| `collectors/muchticket.py` | Articket + CultuTickets: JSON `GET /obtener_eventos/?cantidad_eventos=500`, filtro Mar del Plata (incluye la variante "Mar de Plata"). |
| `collectors/clubtri.py` | Home de clubtri.com = agenda; fechas "Mié 14 de Octubre" con inferencia de año. |
| `lib/schema.py` | `Event`: esquema normalizado único (fuente, título, lugar, fechas ISO, hora, precio, link de compra, etc.). |
| `lib/dates.py` | Parsing de `dd/mm/yyyy` y fechas en español sin año; extracción de hora. |
| `lib/dedupe.py` | Fingerprint lugar+fecha, join exacto por slug de compra y fuzzy de títulos (token_set_ratio, umbral 85). |
| `run_spike.py` | Orquesta collect → normalize → dedupe y escribe `data/`. |
| `tests/` | Pytest: `test_dates.py` y `test_dedupe.py`. |

Cada collector expone `collect() -> list[dict]` (crudo) y `normalize(records) -> list[Event]`. Si una fuente falla, el run sigue con las demás.

## Notas

- Solo lectura sobre sitios externos; UA `cartelera-mdp-spike/0.1 (local research)` y ~1 req/s.
- `.venv/` y `data/raw/` no se versionan; los JSON normalizados sí, como evidencia.
- Decisiones de tuning y limitaciones conocidas: ver `REPORT.md`.
