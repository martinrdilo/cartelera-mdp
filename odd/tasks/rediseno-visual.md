# Rediseño visual de la cartelera (modo claro y oscuro)

Objetivo: reemplazar la grilla de tarjetas grandes por una agenda compacta agrupada por día, con tema claro y oscuro conmutables, manteniendo el sitio estático sin dependencias.
Rama: `feat/rediseno-visual` · Entrega: una PR al terminar · Runner: `.venv/bin/python -m pytest tests/ -q`

## Specs

- **S1 — Tema claro y oscuro.** El sitio debe ofrecer un modo claro y un modo oscuro, con un control visible en el encabezado. La preferencia elegida se recuerda entre visitas; sin elección previa se respeta la preferencia del sistema. Ningún texto puede quedar ilegible en ninguno de los dos temas.
- **S2 — Paleta.** Oscuro: fondo `#080d12`, superficie `#0f1820`, arena `#e7b27c`, verde mar `#46a79b`, texto `#e9eff4`. Claro: papel cálido `#f4f1e9`, superficie `#fffdf8`, arena oscura `#8a4f17`, verde mar `#0b625a`, tinta `#0f1619`. Se descarta el violeta y el blanco puro.
- **S3 — Tarjetas compactas.** El listado principal deja de usar tarjetas con imagen gigante: una fila de agenda muestra hora, miniatura de 56 px, título, sala, precio y acción, con una altura de fila de entre 68 y 80 px en escritorio.
- **S4 — Agenda por día.** El listado se agrupa por fecha y se navega con pestañas de día; cada pestaña muestra su cantidad de eventos. Debe existir una vista "Finde" con los días de la ventana jueves–domingo y una vista "Todo" con todos los eventos futuros. En móvil las pestañas se desplazan horizontalmente.
- **S5 — Filtros y búsqueda.** Se conserva el filtro por gratis y por sala (las tres salas con más eventos) y se agrega búsqueda por texto sobre título y sala, sin recargar la página. Los contadores de cada día se recalculan al filtrar y los días sin resultados quedan deshabilitados. Si no hay resultados se muestra un estado vacío con la opción de limpiar filtros.
- **S6 — Detalle sin salir de la agenda.** Cada fila puede expandir un detalle con todas las fechas del evento, dirección con enlace a mapas, origen de los datos y acciones de compra y de compartir. El control de expansión debe anunciar su estado (`aria-expanded`) y ser alcanzable por teclado.
- **S7 — Flyers reales.** La imagen destacada usa proporción 4:5 y las miniaturas son cuadradas; ninguna imagen se estira. Cuando un evento no tiene flyer, o el flyer falla al cargar, se muestra una miniatura tipográfica con las iniciales del evento en lugar de un hueco gris.
- **S8 — Destacado.** La banda de destacado elige el primer evento del finde, por fecha y hora, que tenga flyer y link de venta; si ninguno cumple ambas condiciones, el primero con flyer; si no hay eventos del finde, la banda no se muestra. Con filtros o búsqueda activos la banda se oculta.
- **S9 — Compatibilidad.** Se conservan la ventana jueves–domingo, el orden por fecha y hora, el descarte de eventos pasados, el JSON-LD, los metadatos sociales, el enlace saliente a la ticketera con `target="_blank" rel="noopener"` y el hook de analítica existente. El build sigue sin red y solo con la stdlib.
- **S10 — Accesibilidad y rendimiento.** Foco visible en ambos temas, contraste AA para texto, `loading="lazy"` en imágenes, sin bloquear el render con JavaScript de terceros y sin fuentes externas: el sitio usa la tipografía del sistema.

## Tasks

- T1 — Shell de la página, tokens de ambos temas, encabezado con conmutador y pie. `S1 S2 S9` · inline · hecho en d435516
- T2 — Filas de agenda, miniaturas, agrupación por fecha y banda de destacado. `S3 S4 S7 S8` · inline · hecho en d435516
- T3 — Pestañas de día, filtros, búsqueda, detalle expansible y estado vacío. `S4 S5 S6` · inline · hecho en d435516
- T4 — Tests del generador y del HTML resultante. `S3–S9` · inline · hecho en d435516 (173 tests)
- T5 — README y verificación final del build. `S9` · inline · hecho en este commit

## Log

- L1 (2026-10-20, pedido original): "Me gustaría que pensemos en un rediseño visual de la aplicación, porque la veo bastante rudimentaria, bastante simple. Me gustaría que sea algo más moderno, más lindo, que atraiga más. […] ¿me puedes proponer opciones? Y no tienes por qué desarrollarlo todo, sino tal vez una captura de pantalla, algo simple que me puedas mostrar para diferenciar qué opciones podemos implementar?"
- L2 (2026-10-20): "La opción A y la opción C me gustan bastante más que la B. […] Lo que no me convence mucho de la opción A es la gama de colores; es como muy fiestero. No sé, ese violeta no me gusta mucho. La opción C no está mal, está bastante bien, pero bueno, quiero ver y seguir explorando opciones."
- L3 (2026-10-20): "Sí, me sigo quedando con una mezcla de A y C. […] Lo que no me gusta de A es que las tarjetas de los eventos son muy grandes; las imágenes son gigantescas. Y de C, bueno, el color blanco, desde ya que no me gusta. Deberíamos agregar un modo oscuro y como un formato simple el C. […] vamos con esa propuesta. ¿Qué podemos hacer? Hagamos el diseño primero."
- L4 (2026-10-20): "El rediseño está bastante bueno. Podríamos ponerle un modo oscuro y un modo claro. Bueno, empecemos a hacerlo. Me gusta la paleta. ¿Qué más necesitas de mi parte? Porque me voy a ir a dormir y quiero que te quedes trabajando."
- Decisiones de implementación (L4 + supuestos, sin bloquear): tipografía del sistema para no agregar dependencias externas; modo por defecto = preferencia del sistema con oscuro como respaldo; destacado elegido por regla determinista (S8); detalle expansible con datos ya disponibles (fechas, dirección, origen), sin descripciones inventadas.

- L5 (2026-10-20, implementación): se completaron T1–T4 en `d435516`. Verificación: `pytest tests/ -q` → 173 passed; `build_site.py --today 2026-10-14` → 145 eventos, 27 del finde, 45 grupos de fecha; `build_site.py --today 2026-10-20` → 117 eventos, 20 del finde (build real sin red). QA visual en navegador: temas claro y oscuro en 1300 px, y layout a 390/768 px; contraste de texto secundario en claro corregido a 4.9:1. Comprobado a mano: persistencia del tema, pestañas de día, chips, búsqueda con salto automático a "Todo", detalle expansible y fallback tipográfico.
- L6 (2026-10-20, correcciones de QA): se quitaron el botón "Sin venta" y la etiqueta "Gratis" duplicada porque ensuciaban la lectura; el destacado pasó a elegirse entre las filas del finde (fecha primaria) para que siempre aparezca en la agenda; en móvil el póster del destacado conserva 4:5 en vez de recortarse a 16:9 y los títulos pueden ocupar dos líneas.
