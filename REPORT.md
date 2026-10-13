# Reporte del spike — extracción de eventos musicales MDP

Corrida real del 2026-10-13 (UTC), end-to-end con `run_spike.py`. Todo lo que sigue sale de `data/` (crudo por fuente, normalizado y clusters con evidencia). Fetches: ~18 requests en el run, ~1 req/s, solo lectura.

## 1. Números

| Fuente | Crudos | Normalizados | Notas |
|---|---:|---:|---|
| Municipal (EMTUR) | 101 | 101 | Música 93 + Festivales 8; Cena/Show/Peña devolvió 0 (sin eventos cargados). 11 páginas de música + 1 de festivales. |
| Articket | 57 | 57 | De 77 eventos del JSON, 57 con lugar en MDP. |
| CultuTickets | 20 | 20 | De 22 del JSON, 20 en MDP. |
| Club TRI | 19 | 19 | Home = agenda completa. |
| **Total** | **197** | **197** | **147 únicos post-dedupe** |

**Dedupe:** 41 clusters de duplicados (91 eventos involucrados, 50 reducciones → 147 únicos).

- 11 clusters con join exacto por slug de compra (ClubTri ↔ Articket), 48 pares por fuzzy.
- 9 clusters triples (municipal + articket + clubtri).
- Por par de fuentes: articket+municipal 15, cultutickets+municipal 13, triple 9, clubtri+municipal 2, articket+clubtri 2.
- Umbral fuzzy: **85** (token_set_ratio sobre títulos normalizados). Justificación en la sección 3.

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
| Tan Biónica @ Polideportivo Islas Malvinas, 21/11 | municipal + articket | fuzzy 100 (alias de venue) |
| Una Obra Redonda @ Brew House, 16/10 | municipal + cultutickets | fuzzy 100 (prefijo de fecha limpiado) |

El patrón fuerte: la agenda municipal republica casi toda la grilla de los venues grandes, y el slug de compra de ClubTri/Articket permite join exacto. 13 clusters dependen de alias de venue (Brew House, Abbey Road, Polideportivo, Villa Victoria) — ver sección 4.

## 3. Calidad de datos

**Resuelto**

- **Encoding:** el municipal se decodifica ISO-8859-1 explícito; acentos intactos ("Álex Ubago", "El Príncipe Idiota", "Rocío Quiroz").
- **Años inferidos (ClubTri):** 19 fechas sin año, regla "año actual, rueda al próximo si está más de 1 día en el pasado". Resultado coherente: 2026-10-14 → 2026-12-12, sin rollovers falsos.
- **CultuTickets publica "Mar de Plata"** (sin la "l") en `lugar`: sin contemplar el typo, el filtro MDP daba 0 eventos. Resuelto aceptando ambas grafías (20 eventos recuperados).
- **Títulos de CultuTickets con prefijo de fecha** ("VIER 16 DE OKTUBRE MDP ..."): se limpian solo para comparar. Sin esto había 1 falso positivo ("Oktubre MdP" ↔ "VIER 16 DE OKTUBRE MDP UNA OBRA REDONDA") y 1 match perdido ("Una Obra Redonda").
- **Precios:** Articket/CultuTickets exponen `entradas_online_desde` (0 nulos); municipal parsea `$` del bloque Entrada (90/101) y gratuidad explícita (6 libres).
- **Umbral 85 tuneado con datos:** con 85 el par "29 de OCT ZICA" vs "JUEV 29 DE OCT ARIEL EL TRAIDOR" (78.3, eventos distintos el mismo día) queda separado. Bajarlo a ~70 los fusionaría.

**Pendiente / conocido**

- **Multi-fecha:** Articket expone solo la primera fecha cuando `unica_fecha=false` (2 casos en esta corrida); municipal con varios rangos guarda min/max (4 casos, ej. Coros Mardelcanto 23/10 → 13/12).
- **Falsos negativos de fuzzy:** "Patricia Luca - Ahora Solo Faltas Tú." vs "Patricia Lucas" (municipal duplicado interno, 72.7) y "Sebastián Molina presenta Vivo Arjona" vs "VIVO ARJONA EN MAR DEL PLATA" (64.6). Quedan sin cluster; la solución es canónico de venues/títulos, no bajar el umbral.
- **Horas discrepantes en clusters:** 4 casos (ej. Cantamos Fatal 22:00 vs 23:30). Falta regla de precedencia (¿vendedor gana?).
- **Municipal sin foto:** 28/101 eventos sin imagen → `source_event_id` por hash (mdp-<sha1>); el resto usa el id embebido en la foto.
- **Sin hora:** 6 eventos municipal (el sitio lista solo el día).
- **Precios nulos:** municipal 11 (texto de entrada vacío/ambiguo); Club TRI 19 (solo estado "Gratis"/"Sólo en puerta"/"Comprar"; el precio vive en el vendedor).
- **Fecha basura en la fuente:** "Recital de Violin y Piano..." (municipal) cargado 29/01/2029 — con $16000 y miércoles 21:00 es casi seguro un typo de la fuente. No se corrige: se reporta.
- **token_set_ratio es permisivo con subconjuntos** (títulos cortos municipal matchean títulos largos del vendedor); aceptable porque el gate lugar+fecha lo contiene.

## 4. Inventario de lugares (38 nombres crudos)

Insumo para el canónico de venues. Variantes del mismo lugar marcadas con →.

| Lugar | Eventos |
|---|---:|
| Club TRI | 42 |
| Vorterix | 20 |
| Ciudad Cultural Brew House → Brew House | 20 |
| Brew House | 15 |
| Teatro Municipal Colón (y "Teatro Municipal Colon") | 13 |
| Arena Mar del Plata | 12 |
| Abbey Road → "Abbey Road - Concert Bar" | 20 |
| Centro de Arte Radio City - Roxy - Melany | 7 |
| Centro Cultural Victoria Ocampo. Villa Victoria → Villa Victoria Ocampo | 6 |
| Bendu | 4 |
| Wolfgang Teatro Bar | 4 |
| La Bancaria - Sala Arturo Jauretche | 3 |
| Chauvin (y "Microteatro Chauvin") | 4 |
| Vinoteca Perrier | 3 |
| Polideportivo Islas Malvinas (y "Estadio Polideportivo Islas Malvinas") | 3 |
| Club 39 Cervecería | 2 |
| Espacio La Rosa | 2 |
| Ogham diagonal | 2 |
| Sheraton Mar del Plata (y "- Auditorium Victoria Ocampo") | 2 |
| Teatro Auditorium - Sala Roberto J. Payró / Sala Gregorio Nachman | 2 |
| Capilla del Divino Maestro - Pías Discípulas | 1 |
| Teatro Tronador | 1 |
| Casa de Madera | 1 |
| Archivo Museo Histórico Municipal Don Roberto T. Barili. Villa Mitre | 1 |
| José Hernandez | 1 |
| Casa del Mar | 1 |
| NH Gran Hotel Provincial | 1 |
| CCAVE | 1 |
| Teatro San Martin | 1 |
| PLAZA DE LA MÚSICA | 1 |
| Lo de Julio Cerveceria | 1 |

Los alias usados hoy en `lib/dedupe.py` son un parche (5 entradas); el canónico real es una tabla con dueño, dirección y salas.

## 5. Limitaciones y próximos pasos

- **Canónico de venues** es el mayor lever de recall: 38 nombres crudos ≈ 30 lugares reales; recupera los 13 clusters que hoy dependen de alias manuales.
- **Expansión multi-fecha** (Articket `unica_fecha=false`, rangos municipal): hoy 1 fecha por evento; el calendario real necesita una fila por fecha.
- **Slug como join de primera clase:** solo ClubTri lo expone; sumar Plateanet/Ticketek daría joins exactos para municipal ↔ vendedores.
- **Fuentes duras fuera de alcance:** Plateanet, Bandsintown, Bombo, Instagram (fases posteriores).
- **Reglas de precedencia** por campo (título, hora, precio) cuando hay conflicto entre fuentes; hoy el cluster guarda todo y decide el consumidor.
- **Cobertura del municipal:** 11 páginas de música son el tope práctico actual; verificar si el tope de 15 páginas alcanza en temporada alta (enero).
