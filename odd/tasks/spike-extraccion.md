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

- [x] **T1** — Collector municipal (`tipo` 11/16/19, ISO-8859-1, paginación, fechas dd/mm/yyyy).
- [x] **T2** — Collector MuchTicket (Articket + CultuTickets; filtro "Mar del Plata" en `lugar`).
- [x] **T3** — Collector ClubTri (HTML; "Mié 14 de Octubre" → ISO con inferencia de año).
- [x] **T4** — Normalizador + esquema común (tests primero en parsing de fechas).
- [x] **T5** — Dedupe (fingerprint venue+fecha + similitud de título / match por slug de compra).
- [x] **T6** — REPORT.md (cobertura, solapamientos, limitaciones) + README de uso.

## Verificación

- `python3 -m pytest tests/ -q` — lógica pura (fechas, dedupe).
- `python3 run_spike.py` — corrida real end-to-end; evidencia en `data/` + REPORT.md.

## Delivery

Local (repo nuevo, sin remoto). Commits por work unit (2 unidades). Estrategia de PR diferida hasta que exista remoto (`ask-on-risk`).

## Presupuesto

Heurística ~400–600 líneas autoradas, sin UI. Spike acotado.

## Evidencia / Progreso

**T1 — Collector municipal.** `collectors/municipal.py` con `collect()`/`normalize()`. Corrida live: 101 eventos (música 93 en 11 páginas, festivales 8; cena/show/peña devolvió 0 eventos). ISO-8859-1 explícito, paginado hasta página vacía (tope 15), `desde/hasta` dd/mm/yyyy (min/max si hay varios rangos), precio/gratuidad y vendedor parseados del bloque Entrada, id desde la foto (28/101 sin foto → id por hash). Parser validado primero offline contra HTML guardado.

**T2 — Collector MuchTicket.** `collectors/muchticket.py`: Articket 57 + CultuTickets 20 eventos en MDP (de 77 y 22 totales del JSON). Hallazgo: CultuTickets publica `"Mar de Plata"` (sin la "l") — sin contemplar el typo el filtro devolvía 0. Un host caído no aborta al otro. Limitación documentada: `unica_fecha=false` expone solo la primera fecha (2 casos).

**T3 — Collector ClubTri.** `collectors/clubtri.py`: 19 eventos con hora, estado de precio y link externo; 11 links apuntan a slugs de Articket (señal de join exacto). Fechas "Mié 14 de Octubre" inferidas a ISO: rango resultante 2026-10-14 → 2026-12-12, sin rollovers falsos.

**T4 — Normalizador + esquema.** `lib/schema.py` (`Event`, 18 campos) y `lib/dates.py` (dd/mm/yyyy, español sin año con inferencia, extracción de hora). TDD: tests primero (`tests/test_dates.py`) con RED observado (`ModuleNotFoundError`), luego implementación → GREEN. `tests/conftest.py` agrega el root al `sys.path`.

**Verificación parcial (al cierre de T1–T4):** `.venv/bin/python -m pytest tests/ -q` → `42 passed`. Los collectors se validaron con la corrida live completa (ver T5/T6).

**T5 — Dedupe.** `lib/dedupe.py` + `tests/test_dedupe.py` (TDD, RED observado en los tests de alias y de prefijos de fecha). Corrida live: **41 clusters** (91 eventos involucrados, 197 → 147 únicos); 11 por slug exacto ClubTri↔Articket, 9 triples municipal+articket+clubtri. Umbral fuzzy 85 tuneado con el corpus: 78.3 separa eventos distintos el mismo día, y el falso positivo detectado ("Oktubre MdP") se eliminó limpiando prefijos de fecha en títulos de CultuTickets (además recuperó "Una Obra Redonda"). Alias de venues (Brew House, Abbey Road, Polideportivo, Villa Victoria) como parche documentado hasta el canónico.

**T6 — Reporte + README.** `REPORT.md` con números reales (197 crudos/normalizados, 147 únicos, 41 clusters, inventario de 38 lugares crudos) y limitaciones (multi-fecha, precios nulos, horas discrepantes, fecha 2029 typo de la fuente). `README.md` con el camino rápido (venv → pytest → run_spike).

**Verificación final:** `.venv/bin/python -m pytest tests/ -q` → `42 passed`; `.venv/bin/python run_spike.py` → `TOTAL normalized=197 unique=147` + `duplicate clusters: 41`.
