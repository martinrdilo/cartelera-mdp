# Reporte — extracción de eventos musicales MDP (pipeline v2)

Corrida real del 2026-10-14 (UTC), end-to-end con `run_pipeline.py` (rename del `run_spike.py` del spike). Todo lo que sigue sale de `data/` (crudo por fuente, normalizado, clusters y `last_run.json`). Fetches: ~18 requests en el run, ~1 req/s, solo lectura.

## 1. Números

| Fuente | Crudos | Normalizados | Notas |
|---|---:|---:|---|
| Municipal (EMTUR) | 101 | 101 | Música 93 + Festivales 8; Cena/Show/Peña devolvió 0 (sin eventos cargados). 11 páginas de música + 1 de festivales. |
| Articket | 57 | 57 | De 77 eventos del JSON, 57 con lugar en MDP. |
| CultuTickets | 20 | 20 | De 22 del JSON, 20 en MDP. |
| Club TRI | 19 | 19 | Home = agenda completa. |
| **Total** | **197** | **197** | **146 únicos post-dedupe** |

**Antes/después (spike → v2):**

| Métrica | Spike | v2 |
|---|---:|---:|
| Únicos post-dedupe | 147 | **146** |
| Clusters de duplicados | 41 | 41 |
| Pares en clusters | 59 | 60 |
| Eventos multi-fecha (`occurrences` > 1) | 0 | **13** |
| Fechas de ocurrencia totales | 197 | **237** |
| Venues resueltos por registry | — | **197/197** (42 strings crudos → 30 venues) |
| `recurrence_unknown` / `multi_date_incomplete` | — | 0 / 0 |

**Dedupe v2:** 41 clusters (92 eventos involucrados, 51 reducciones → 146 únicos); 11 pares con join exacto por slug (ClubTri ↔ Articket) y 49 por fuzzy. Por fuentes: articket+municipal 15, cultutickets+municipal 13, triple 9, clubtri+municipal 2, articket+clubtri 2. 10 clusters tienen 3+ eventos.

- **Match nuevo de v2:** `municipal:Tan Biónica` (rango 21–22/11) ↔ `articket:TAN-BIONICA-EN-MAR-DEL-PLATA-22-11` por intersección de `occurrences`. El vendedor publica una página por fecha y el gate viejo (fecha de inicio) no veía la segunda. El cluster quedó de 3 miembros (las dos páginas de Articket + municipal).
- **Sin regresiones:** los 59 pares del spike siguen todos; el diff de pares da 0 perdidos y 1 agregado.

**Multi-fecha v2:** 13 eventos → 40 fechas extra:
- Municipal: 133 fechas de ocurrencia en total (11 eventos multi-fecha expandidos a 43, rangos con días de semana).
- Articket: 2 eventos `unica_fecha=false` enriquecidos a 10 fechas (MAR DEL ENCIENDE RECARGADO: 6 funciones; ZAMBAYONNY: 4).

## 2. Cobertura

| Fuente | Qué aporta | Rol en la cartelera |
|---|---|---|
| Municipal (EMTUR) | 101 eventos, 38 lugares, precios en texto y gratuidad; sin links de compra. | La red más amplia: publica la agenda de salas y también de Club TRI, Vorterix, Abbey Road y Brew House. |
| Articket | 57 eventos con slug, precio desde, imagen y link de compra. | Vendedor dominante en MDP (Abbey Road, Vorterix, Club TRI, Polideportivo). |
| CultuTickets | 20 eventos, casi todos de Ciudad Cultural Brew House. | Cubre Brew House, que no aparece en Articket. |
| Club TRI | 19 eventos con hora, estado de precio y link de compra externo. | Detalle fino de un venue clave; 11 de sus links son slugs de Articket. |

**Solapamientos verificables** (título — fuentes, evidencia):

| Evento | Fuentes | Evidencia |
|---|---|---|
| Dante Spinetta @ Club TRI, 14/11 | municipal + articket + clubtri | slug `dante-spinetta-club-tri` + fuzzy 100 |
| An Espil @ Club TRI, 20/11 | municipal + articket + clubtri | slug `an-espil-en-club-tri` + fuzzy 100 |
| Rey Garufa @ Brew House, 05/12 | municipal + cultutickets | fuzzy 100 (alias de venue) |
| Tan Biónica @ Polideportivo Islas Malvinas, 21–22/11 | municipal + articket (x2) | intersección de `occurrences` + fuzzy 100 |
| Una Obra Redonda @ Brew House, 16/10 | municipal + cultutickets | fuzzy 100 (prefijo de fecha limpiado) |

El patrón fuerte se mantiene: la agenda municipal republica casi toda la grilla de los venues grandes, y el slug de compra de ClubTri/Articket permite join exacto. Los clusters que dependían de alias de venue (Brew House, Abbey Road, Polideportivo, Villa Victoria, Sheraton) ahora los sostiene el registry, sin parches hardcodeados.

## 3. Calidad de datos

**Resuelto**

- **Encoding:** el municipal se decodifica ISO-8859-1 explícito; acentos intactos ("Álex Ubago", "El Príncipe Idiota", "Rocío Quiroz").
- **Años inferidos (ClubTri):** 19 fechas sin año, regla "año actual, rueda al próximo si está más de 1 día en el pasado". Resultado coherente: 2026-10-14 → 2026-12-12, sin rollovers falsos.
- **CultuTickets publica "Mar de Plata"** (sin la "l") en `lugar`: sin contemplar el typo, el filtro MDP daba 0 eventos. Resuelto aceptando ambas grafías (20 eventos recuperados).
- **Títulos de CultuTickets con prefijo de fecha:** se limpian solo para comparar; sin esto había 1 falso positivo y 1 match perdido.
- **Precios:** Articket/CultuTickets exponen `entradas_online_desde` (0 nulos); municipal parsea `$` del bloque Entrada (90/101) y gratuidad explícita (6 libres).
- **Umbral 85 tuneado con datos:** el par "29 de OCT ZICA" vs "JUEV 29 DE OCT ARIEL EL TRAIDOR" (78.3, eventos distintos el mismo día) queda separado; bajarlo a ~70 los fusionaría.
- **Multi-fecha municipal (v2):** regla en `lib/occurrences.py`: un segmento con días de semana listados expande una ocurrencia por día dentro del rango; un día único es fecha exacta y siempre rinde su fecha (la etiqueta de día de semana de la fuente se ignora porque no es confiable: 3 eventos del corpus con etiqueta inconsistente quedaban en `occurrences: []` silencioso; corregido, +3 fechas); un rango multi-día sin días de semana no se inventa (`occurrences: []` + `recurrence_unknown: true`), y una expansión multi-día sin fechas también queda flageada. En el corpus real los 11 eventos multi-fecha traen días de semana: 0 `recurrence_unknown`.
- **Multi-fecha Articket (v2):** la página de detalle lista todas las funciones en el `<select name="fechas_evento">`; el JSON-LD `schema.org/Event` solo trae `startDate`/`endDate` (verificado en vivo: con `unica_fecha=false` igual expone una sola fecha). Se usa el select como fuente primaria y el JSON-LD como fallback (primera fecha + `multi_date_incomplete: true`). 2/2 eventos enriquecidos, 0 incompletos.
- **Canónico de venues (v2):** `data/venues.json` (30 venues) + `lib/venues.py` resuelven los 42 strings crudos distintos del corpus (197/197 eventos). La normalización (casefold, sin acentos, sin puntuación) resuelve variantes como "Teatro Municipal Colon" sin alias extra.

**Pendiente / conocido**

- **Falsos negativos de fuzzy:** "Patricia Luca - Ahora Solo Faltas Tú." vs "Patricia Lucas" (municipal duplicado interno, 72.7) y "Sebastián Molina presenta Vivo Arjona" vs "VIVO ARJONA EN MAR DEL PLATA" (64.6). Quedan sin cluster; la solución es canónico de títulos, no bajar el umbral.
- **Fallback de fechas:** si un evento no tiene `occurrences` (rango sin recurrencia o detalle fallido), el dedupe vuelve a igualdad de `date_start`; un vendedor con una fecha distinta al inicio del rango podría no matchear. Es la regla conservadora documentada.
- **Dependencia del select de Articket:** si cambia la estructura del detalle, el fallback JSON-LD deja solo la primera fecha (+ flag); la corrida no se rompe.
- **Horas discrepantes en clusters:** 4 casos (ej. Cantamos Fatal 22:00 vs 23:30). Falta regla de precedencia (¿vendedor gana?).
- **Municipal sin foto:** 28/101 eventos sin imagen → `source_event_id` por hash (mdp-<sha1>); el resto usa el id embebido en la foto.
- **Sin hora:** 6 eventos municipal (el sitio lista solo el día).
- **Precios nulos:** municipal 11 (texto de entrada vacío/ambiguo); Club TRI 19 (solo estado "Gratis"/"Sólo en puerta"/"Comprar"; el precio vive en el vendedor).
- **Fecha basura en la fuente:** "Recital de Violin y Piano..." (municipal) cargado 29/01/2029 — con $16000 y miércoles 21:00 es casi seguro un typo de la fuente. No se corrige: se reporta.
- **token_set_ratio es permisivo con subconjuntos** (títulos cortos municipal matchean títulos largos del vendedor); aceptable porque el gate venue+fecha lo contiene.
- **Clusters multi-fecha son transitivos:** las dos páginas por fecha de un vendedor se unen al evento municipal vía union-find y quedan en un cluster de 3+ miembros; el consumidor decide con `dates` (unión) cómo renderizar una fila por fecha.

## 4. Canónico de venues

En v2 `data/venues.json` tenía 30 venues con los alias observados en `data/raw/*.json` y la dirección cuando el corpus la expone. `lib/venues.py` resuelve por normalización exacta + alias, con fallback a la parte antes de la primera coma (los strings crudos traen dirección). Cobertura: 42 strings crudos distintos → 0 sin resolver; los no conocidos caen al nombre normalizado (nunca bloquean el dedupe).

Grupos de alias notables:

| Venue | Variantes observadas |
|---|---|
| Ciudad Cultural Brew House | "Brew House", "Ciudad Cultural Brew House" |
| Abbey Road | "Abbey Road", "Abbey Road - Concert Bar" |
| Teatro Municipal Colón | "Teatro Municipal Colón" / "Colon" (los acentos los resuelve la normalización) |
| Villa Victoria Ocampo | "Villa Victoria Ocampo", "Centro Cultural Victoria Ocampo. Villa Victoria" |
| Polideportivo Islas Malvinas | "Polideportivo Islas Malvinas", "Estadio Polideportivo Islas Malvinas" |
| Chauvin | "Chauvin", "Microteatro Chauvin" |
| Teatro Auditorium | "Teatro Auditorium - Sala Roberto J. Payró" y "Sala Gregorio Nachman" comparten venue |
| Sheraton Mar del Plata | "Sheraton Mar del Plata", "Sheraton Mar del Plata - Auditorium Victoria Ocampo" |

**Oddity del Sheraton:** el municipal publica el hall como "Sheraton Mar del Plata - Auditorium Victoria Ocampo" (Alem 4221). Es el Sheraton, no Villa Victoria (Matheu 1851): el registry los mantiene separados y hay test de que no se cruzan.

## 5. Limitaciones y próximos pasos

- **Canónico de venues** quedó hecho: 42 strings → 30 venues, 100% resuelto, sin lista hardcodeada en el dedupe.
- **Multi-fecha** quedó hecho para lo que las fuentes exponen (rangos municipal con días + detalle Articket). Si aparece un rango sin recurrencia, el sistema lo flagea en vez de inventar.
- **Slug como join de primera clase:** solo ClubTri lo expone; sumar Plateanet/Ticketek daría joins exactos para municipal ↔ vendedores.
- **Fuentes duras fuera de alcance:** Plateanet, Bandsintown, Instagram (fases posteriores). Bombo quedó cubierto en la ola 1 (v3).
- **Reglas de precedencia** por campo (título, hora, precio) cuando hay conflicto entre fuentes; hoy el cluster guarda todo y decide el consumidor.
- **Cobertura del municipal:** 11 páginas de música son el tope práctico actual; verificar si el tope de 15 páginas alcanza en temporada alta (enero).
- **Operación:** `scripts/daily.sh` + `data/last_run.json` dejan la corrida diaria lista para cron/systemd; falta decidir dónde corre (deploy) y sumar alerta si el exit code no es 0.

## 6. Ola 1 de fuentes (v3)

Corrida real del 2026-10-23T00:26Z, end-to-end con `run_pipeline.py` (482 s; el enriquecimiento de Punto con una ficha por evento es la parte lenta). Fetch real, solo lectura, ~1 req/s.

| Fuente | Crudos | Normalizados | Notas |
|---|---:|---:|---|
| Municipal (EMTUR) | 80 | 80 | Música + festivales; la agenda municipal cambió respecto de v2 |
| Articket | 67 | 67 | Vendedor dominante; 9 funciones nuevas de Ticketek se solapan con éste |
| CultuTickets | 19 | 19 | Brew House |
| Club TRI | 19 | 19 | Detalle de sala |
| Venti | 13 | 13 | Quba, Sheraton/La Vin, Zwan, Casinos; filtro por coordenadas |
| Ticketek | 9 | 9 | Bendu Arena, Teatro Tronador, Radio City |
| Bombo | 7 | 7 | Mute Club de Mar y The County; se descartó el "Poker Pass" (bundle, no evento) |
| Punto Mar del Plata | 84 | 84 | Agenda local de música; link de venta desde el JSON-LD de cada ficha |
| **Total** | **298** | **298** | **187 únicos post-dedupe** |

- **81 clusters** de duplicados (192 eventos involucrados, 111 reducciones → 187 únicos). Los clusters nuevos incluyen tripletes municipal+punto+ticketek (Dillom, Divididos, Abel Pintos, La Delio Valdez/La K'onga) y municipal+punto+venti (La Vin, Vinmusic).
- **Cobertura nueva:** Arena Mardel Plata (Venti/Ticketek/Punto), Bendu Arena (Ticketek/Punto), Mute Club de Mar y The County (Bombo), Quba/Zwan/Casinos (Venti), y 84 eventos de música de Punto con salas chicas que la agenda municipal no publica.
- **Dedupe v3:** hosts nuevos (`venti.live`, `wearebombo.com`, `tuentrada.com`, `plateanet.com`, `unica-cartelera.com.ar`), limpieza de fechas embebidas en títulos ("22.10", "31/10"), contención de tokens significativos y prefijo de artista. Casos que antes quedaban duplicados y ahora cierran: Diego Torres, Sergio Dalma, Baglietto Vital, Patricia Luca/Lucas, Cruzando el Charco, Martín Masiello. El sitio agrega un guard final (mismo venue + título normalizado + fecha compartida) y la corrida real verifica **0 tripletas duplicadas**.
- **Venues:** `data/venues.json` pasa de 30 a 40 venues (Arena, Bendu Arena, Mute, The County, Quba, Zwan, Casinos, Auditorium Laureti Puerto, Mole Club, etc.). Resolución: 295/298; los 3 restantes son nombres de productora de Bombo (`SINERGIA`, `Antesala`), que se muestran tal cual y no bloquean el dedupe.
- **Pendiente:** 16 buckets venue+fecha tienen más de una fila; la mayoría son funciones distintas (dos shows en Club TRI, dos en Colón, dos Candlelight). Quedan falsos negativos difíciles por títulos de artistas con spelling muy distinto. La ola 2 (Auditorium, Colón, TuEntrada) y la ola 3 (Plateanet, medios/redes) siguen pendientes.
