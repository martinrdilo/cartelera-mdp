# Web v1 — "Este finde" + deploy (Fase 2)

**Estado:** En curso · **Repo:** local + GitHub público (`cartelera-mdp`) · **Fecha:** 2026-10-14
**Contexto:** Fase 2 del MVP (`docs/mvp.md`). Decisiones del usuario (2026-10-14): nombre placeholder "Cartelera MDP" · repo público en GitHub · subdominio gratis · deploy público sin promocionar.

## Objetivo

1. Web v1 estática generada por el pipeline: hero **"Este finde"** (jue–dom), lista completa con filtros (fecha / lugar / gratis-pago), tarjetas de evento con **"Sacar entrada"** (link-out) y compartir. Mobile-first.
2. Deploy público en **GitHub Pages** con actualización diaria automática (GitHub Actions: pipeline + build + deploy).
3. Hooks de analítica listos (sin proveedor todavía).

## Alcance

- **In:** `build_site.py` + `site_assets/` + tests; workflow `.github/workflows/deploy.yml`; README; sitio generado en `site/` (gitignoreado).
- **Out:** dominio propio, proveedor de analítica, páginas por venue, IG/WhatsApp (Fases 3–4), alertas.

## Restricciones

- No correr `run_pipeline.py` en el build local (los datos están frescos del 2026-10-13; el CI sí lo corre).
- No hacer push (el parent maneja el remoto).
- Código/HTML/JS en inglés; copy visible del sitio en español rioplatense.
- Compatible con Python 3.12 (el CI usa 3.12).

## Criterios de aceptación

- [ ] `python3 build_site.py` genera `site/` con hero "Este finde" + lista + filtros + links de compra.
- [ ] Ventana "este finde" (jue–dom) con tests por día de la semana.
- [ ] Filtros client-side (fecha/lugar/gratis) funcionando.
- [ ] Hooks de outbound (`data-outbound`) + botón compartir WhatsApp.
- [ ] SEO básico (title/meta/JSON-LD) y accesibilidad mínima.
- [ ] Workflow de deploy (push + cron diario + dispatch) en `.github/workflows/`.
- [ ] Tests verdes + README actualizado.

## Tareas

- [ ] **T1** — `build_site.py`: carga datos, filtra futuros, genera `site/` (index + assets).
- [ ] **T2** — Ventana "este finde" jue–dom (lógica + tests por día).
- [ ] **T3** — Lista + filtros + tarjetas + compartir + hooks.
- [ ] **T4** — SEO + accesibilidad + empty states.
- [ ] **T5** — Workflow GitHub Actions (pipeline best-effort + build + deploy Pages, cron 11:00 UTC).
- [ ] **T6** — Tests + README + verificación local.

## Verificación

- `python3 -m pytest tests/ -q`
- `python3 build_site.py` — números observados (eventos incluidos, finde, archivos).

## Delivery

GitHub público (`cartelera-mdp`) + GitHub Pages. Commits por work unit. Sin PR.

## Presupuesto

Heurística ~600–900 líneas (generador + HTML/CSS/JS + tests).

## Evidencia / Progreso

_(se actualiza al cierre de cada tarea)_
