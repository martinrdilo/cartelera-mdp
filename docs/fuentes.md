# Fuentes de datos y tipo de venta

**Estado:** Documentado (2026-11-21) · **Evidencia:** `data/events_normalized.json` de la corrida terminada el 2026-11-19T03:05:45Z (601 eventos normalizados, 324 únicos post-dedupe, 16 fuentes).

Clasificación de las 16 fuentes del pipeline según quién cobra la entrada. Sirve para separar lo que es **venta directa** de lo que es descubrimiento.

## 1. El modelo ya distingue dos niveles

- `source` — de qué collector salió el evento: dónde lo descubrimos.
- `seller` — quién vende la entrada: se deriva del host del link de compra con `lib/sellers.py`.

`lib/sellers.py` lo declara: *"A collector that sees an outbound ticket link uses this map to fill `seller`"*. Es decir, la venta directa es una propiedad del **vendedor**, no de la fuente; la fuente solo dice dónde lo encontramos.

## 2. Venta directa (la fuente **es** la ticketera)

En estas 8 fuentes el `seller` coincide con la propia fuente en el 100% de sus filas: publican su inventario y cobran ellas.

| Fuente | Módulo | Filas | seller observado |
|---|---|---:|---|
| Articket | `muchticket.py` | 53 | Articket 53/53 |
| Venti | `venti.py` | 23 | Venti 23/23 |
| CultuTickets | `muchticket.py` | 19 | CultuTickets 19/19 |
| Chauvin (Fanz) | `fanz.py` | 12 | Chauvin 12/12 |
| Ticketek | `ticketek.py` | 11 | Ticketek 11/11 |
| Bombo | `bombo.py` | 7 | Bombo 7/7 |
| Passline | `passline.py` | 7 | Passline 7/7 |
| TuEntrada | `tuentrada.py` | 1 | TuEntrada 1/1 |

**Subtotal: 133 filas.**

## 3. No es venta directa — carteleras y agendas (5)

Descubren eventos y redirigen a un vendedor ajeno. Son las "otras carteleras" del proyecto.

| Fuente | Filas | A quién redirige |
|---|---:|---|
| Qué Hacemos | 146 | Metabuscador con API abierta: Passline 29, Articket 29, Dogma 16, 45 sin vendedor |
| Municipal (EMTUR) | 81 | Articket 19, Venti 6, Ticketek 6, 19 sin vendedor |
| Eleven Flow | 78 | Articket 27, Chauvin 11, Passline 8, Venti 7; única vía observada a eventos que solo vende Plateanet |
| Punto Mar del Plata | 68 | Articket 26, Venti 9, Ticketek 8, 9 sin vendedor |
| Cual Pinta | 61 | Bombo 8, Articket 6, CultuTickets 5, **30 sin link de venta** |

**Subtotal: 434 filas.**

## 4. No es venta directa — venues con programación propia (3)

Ni ticketeras ni carteleras: publican la agenda de su sala y la venta ocurre en boletería o en una ticketera ajena.

| Fuente | Filas | Venta |
|---|---:|---|
| Club TRI | 13 | Articket 8, Passline 1, 4 sin vendedor |
| Teatro Colón | 11 | 11/11 sin seller: boletería propia y entrada libre |
| Auditorium | 10 | Plateanet 8, 2 sin vendedor |

**Subtotal: 34 filas.**

133 + 434 + 34 = 601 filas, el total de la corrida.

## 5. Mapa módulo → fuente (15 módulos, 16 fuentes)

`collectors/` tiene 15 módulos y el pipeline escribe 16 archivos en `data/raw/`:

- `muchticket.py` → `articket.json` y `cultutickets.json` (dos fuentes, un módulo).
- `fanz.py` → `chauvin.json` (tenant de Chauvin en la plataforma Fanz).
- El resto es 1:1.

Contar fuentes por módulo da 15; contar por `data/raw/*.json` da 16.

## 6. Por qué un binario por fuente no alcanza

Una etiqueta "venta directa sí/no" a nivel de collector clasifica mal tres casos reales:

- **Club TRI** es venue, pero 8 de sus 13 filas se compran por Articket.
- **Auditorium** es venue, pero 8 de sus 10 filas se compran por Plateanet.
- **Cual Pinta** es cartelera, pero 30 de sus 61 filas no tienen ningún link de venta.

Si lo que se quiere es saber si el usuario **puede comprar en el sitio sin salir**, la respuesta es por evento (`seller` propio vs. tercero), no por fuente.

Además, filtrar por "solo venta directa" cuesta inventario: se pierden 434 de 601 filas, y con ellas la mayor parte de la oferta de salas chicas que solo publican Punto, Cual Pinta y Qué Hacemos.

## 7. Estado del cambio

La clasificación quedó **solo documentada**: no se agregó ningún campo al esquema y `data/` quedó intacto. Cualquier implementación futura tiene que elegir entre etiqueta por fuente (3 tipos) o derivación por evento desde `lib/sellers.py`.

El relevamiento sí destapó dos defectos de código, corregidos el mismo día (2026-11-21):

**1. `collectors/clubtri.py`** ahora guarda el link propio de la tarjeta como `raw_url` cuando no es un link de ticketera. Antes todas las tarjetas quedaban con `https://clubtri.com/` como origen, así que los 4 eventos gratis de Club TRI (El Fuego Sagrado, Noche de Salsa, Ciclo Costa Cannabis, Pistilo 27 Aniversario) no tenían ni venta ni link al evento: sólo el home del club. Con este cambio, cada uno apunta a su post de Instagram, y las tarjetas con ticketera conservan `ticket_url` y el origen anterior. Toma efecto en `data/` recién en la próxima corrida del pipeline; los snapshots actuales todavía tienen el `raw_url` viejo.

**2. `build_site.py`** dejó de enlazar páginas que no son de un evento. La agenda municipal está paginada por fecha, así que la página registrada al colectar deja de contener el evento a los pocos días (verificado en vivo: el evento de Javier Santaolalla estaba en `pagina=4` cuando se colectó y hoy está en `pagina=3`); Articket y CultuTickets exponen un endpoint JSON como `raw_url`, Venti una API, y Club TRI publicaba el home del club. Ahora `is_event_page()` descarta esos casos y la «Fuente» usa la ficha de mayor prioridad, o la página del evento en la ticketera, o el nombre sin link. `is_event_page()` sólo acepta `http`/`https` con un path real: un `ftp://…` o un home con query (`https://host/?p=1`) nunca es ficha; la excepción de Colón (`/colonprogramacion` en `mardelplata.gob.ar`, con o sin `www.` y con o sin barra final) sigue valiendo. Los marcadores de listado se comparan contra host y path, sin query ni fragmento: que un parámetro de la URL mencione `/obtener_eventos` no convierte una ficha real en listado, y el endpoint se rechaza igual con o sin barra final, con query y con fragmento.

Build del 2026-11-21 (`--today 2026-11-21`) sobre el head que cierra este relevamiento: **285 filas**, **264 resuelven una página de fuente**, todas a fichas reales (antes 318, de las cuales 119 eran endpoints, listados paginados o homes). De esas 264, **145 se muestran como link** «Ver en …» y **119 quedan como texto plano** porque la página elegida es la misma URL del CTA de compra (`source_url == ticket_url`): enlazarla otra vez duplicaba la acción de compra que la fila ya ofrece. De las 145 enlazadas, **7 apuntan a `colonprogramacion`**.

Quedan **21 filas sin link de fuente**: **18 municipal** (EMTUR no publica ficha por evento) y **3 de Club TRI**.

Tres cambios de la tanda sólo llegan al sitio después de **una corrida real del pipeline**; `data/` no se regeneró a mano:

- **`venue_url`** (sitio de la sala capturado del panel municipal): el collector ya lo guarda, pero `data/events_normalized.json` todavía no tiene el campo, así que hoy no se renderiza la línea «Sala».
- **Los 6 duplicados probados** de venues/dedupe: son aliases en `data/venues.json` y `lib/dedupe.py` los aplica al armar los clusters, o sea que las filas recién se unen cuando el pipeline reescribe `data/events_deduped.json` (que es lo que lee `build_site.py`).
- **`last_run.json`** sigue describiendo la corrida del 2026-11-19 (511 venues resueltos, 90 sin resolver) aunque el registro ya resuelva 587 de 601.

Estado de la suite en el head actual: **750 tests pasan, 1 falla** (`test_build_site.py::test_known_ticket_url_is_linked`). Esa falla es **previa a estos cambios**: depende del calendario, porque `_anchor_today()` avanza con la fecha y el evento que la aserción busca queda en el pasado.

## 8. Follow-ups detectados al relevar

- **Venti con dos nombres.** `lib/sellers.py` mapea `venti.live` → `"Venti"`, y el collector `venti.py` produce `Venti`, pero `municipal` deja `"Venti.live"` en 6 filas. Hay que unificar el string para que agrupe bien.
- **`source` no refleja al vendedor real en Qué Hacemos.** Sus 146 filas quedan como `source=quehacemos` aunque el `seller` sea Plateanet, Dogma, Bandsintown o Alpogo. Es correcto por diseño, pero engaña si se cuenta cobertura por vendedor.
- **90 venues sin resolver** en la última corrida (`last_run.json`: 511 resueltos, 90 sin resolver), en su mayoría nombres de productora y zonas.
