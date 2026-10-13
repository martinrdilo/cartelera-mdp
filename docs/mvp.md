# MVP — Cartelera de eventos musicales de Mar del Plata

**Estado:** Definido (2026-10-13) · **Encuadre:** Piloto de validación (~3–4 semanas) · **Repo:** `cartelera-mdp`

> Mismo método que `docs/creacion-productos` (patineta → lanzar → medir → decidir), con canales locales (IG/WhatsApp/grupos) en lugar de Product Hunt/Reddit, y mercado MDP a propósito.

## 1. La apuesta

> "Todo lo que suena en Mar del Plata, en un solo lugar: qué hay este finde, dónde, cuánto sale y el link para sacar la entrada."

El uso real es **semanal y desde el celular**: alguien decide qué hacer el fin de semana. El piloto valida esa promesa con la menor superficie posible.

## 2. Problema y evidencia

- **Problema:** la oferta musical de MDP está fragmentada entre ticketeras, agenda municipal, sitios de venues e Instagram; no existe una cartelera music-first con links de compra (market scan del 2026-10-13).
- **Evidencia técnica (spike, verificada):** 3 fuentes automatizables → 197 eventos → **147 únicos** tras dedupe (41 clusters; 11 joins exactos por slug). Una corrida completa ≈ 18 requests. Detalle en `REPORT.md`.

## 3. Usuario y momento de uso

El que decide *"¿qué hago este finde?"* — residente o visitante. Uso semanal, mobile, en ráfagas (jueves a domingo).

## 4. Alcance

**Entra (patineta):**
- Web mobile-first: vista hero **"Este finde"** (jue–dom) + lista completa con filtros simples (fecha, lugar, gratis/pago) + detalle de evento con **"Sacar entrada"** (link-out a la ticketera) + botón compartir.
- Pipeline v2: canónico de venues, multi-fecha (una fila por fecha), corrida diaria automática.
- Digest semanal en **IG + canal de WhatsApp**.
- Analítica simple (visitas, clics a ticketeras).

**Queda afuera (v2+):** pagos, cuentas de usuario, seguir artistas/alerts, app nativa, filtro por género (requiere etiquetado), páginas ricas por venue, fuentes duras (Plateanet/Bombo/Bandsintown/IG automático), self-serve para venues.

## 5. Datos (pipeline)

- Fuentes automatizadas: municipal EMTUR (la más amplia, incluye gratis), MuchTicket (Articket + CultuTickets), ClubTri.
- Carril manual para huecos (venues que solo publican en IG, ej. CCAVE): carga a mano en el repo/panel.
- Cobertura actual: mayoría de lo pago de venues grandes + gratis municipal. Verificar el tope de paginación municipal en temporada alta (enero).
- Legal: municipal público (atribución si se usa el dataset ODbL); ToS de los sitios MuchTicket a revisar — les mandamos tráfico, posición favorable para pedir permiso formal.

## 6. Modelo de ingresos (hipótesis a validar)

- **Fase 1 (piloto): gratis para el usuario.** La audiencia es el activo.
- **Fase 2 (post-tracción): B2B** — visibilidad paga para venues/producers (destacados en el digest y la web), acuerdos con ticketeras, sponsors locales.
- **Validación en el piloto:** 5–10 charlas con venues/producers: *"¿pagarías por aparecer destacado donde la gente busca qué hacer?"*. Éxito = ≥ 2 con interés concreto (reunión agendada, propuesta pedida, compromiso). No se construye nada pago todavía.

## 7. Distribución

- IG (cuenta + carrusel del finde) y canal de WhatsApp: donde está la audiencia y donde los venues ya publican.
- SEO local ("shows en Mar del Plata este fin de semana"): casi gratis con los datos ya generados.
- Loop de compartir desde la web (WhatsApp primero).

## 8. Métricas y criterios de decisión (a las ~4 semanas)

| Métrica | Señal tentativa |
|---|---|
| Visitas únicas / semana | ≥ 300 |
| Clics a ticketeras / finde | ≥ 50 |
| Seguidores IG + WhatsApp | ≥ 300 |
| Recurrencia (vuelve la semana siguiente) | ≥ 25% |
| Charlas con venues | 5–10 hechas, ≥ 2 con interés concreto |

**Decisión:** SEGUIR (≥ 3 señales) → invertir más (fuentes duras, v2). ITERAR (1–2) → ajustar propuesta/canal y correr otra ronda corta. ARCHIVAR (0) → aprendizaje registrado, siguiente producto (regla de la guía). Los números son tentativos: se ajustan antes de arrancar.

## 9. Plan (~15 días)

1. **Pipeline v2** — canónico de venues + multi-fecha + cron diario (extiende el spike).
2. **Web v1 + deploy** — estática regenerada por la corrida diaria (cero costo de infra).
3. **IG + WhatsApp + primer digest** — y definimos nombre + handle.
4. **Lanzamiento suave** — grupos, boca a boca, venues + charlas + tablero de métricas.

## 10. Riesgos

- **Adopción** (el #1): mitigado con distribución como parte del MVP, no como extra.
- **Mantenimiento:** los scrapers se rompen; ~1–2 h/semana de curaduría + alertas de corrida.
- **Legal:** ToS MuchTicket (revisar + pedir permiso); ODbL municipal con atribución; IG solo manual.
- **Estacionalidad:** enero es el test grande (turismo + volumen); verificar paginación municipal.

## 11. Costos

- Infra: ~US$0 (estático + cron gratis). Dominio: ~US$10–15/año (para IG/SEO).
- Tiempo: build ~2–3 semanas de trabajo asistido + 1–2 h/semana de curaduría.

## Pendientes

- Nombre + handle (Fase 3).
- Dominio.
- Números finales de métricas (ajustar antes de arrancar).
- Revisión de ToS de MuchTicket.

## Referencias

- `REPORT.md` — números y limitaciones del spike.
- `odd/tasks/spike-extraccion.md` — tareas y verificación del spike.
- Investigación de fuentes (2026-10-13) — factibilidad por fuente (Engram: `research/mdp-music-events-aggregator`).
