# Web v1 — "Este finde" + deploy (Fase 2)

**Estado:** Completado (2026-10-14) · **Repo:** local + GitHub público (`cartelera-mdp`) · **Fecha:** 2026-10-14
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

- [x] `python3 build_site.py` genera `site/` con hero "Este finde" + lista + filtros + links de compra.
- [x] Ventana "este finde" (jue–dom) con tests por día de la semana.
- [x] Filtros client-side (fecha/lugar/gratis) funcionando.
- [x] Hooks de outbound (`data-outbound`) + botón compartir WhatsApp.
- [x] SEO básico (title/meta/JSON-LD) y accesibilidad mínima.
- [x] Workflow de deploy (push + cron diario + dispatch) en `.github/workflows/`.
- [x] Tests verdes + README actualizado.

## Tareas

- [x] **T1** — `build_site.py`: carga datos, filtra futuros, genera `site/` (index + assets).
- [x] **T2** — Ventana "este finde" jue–dom (lógica + tests por día).
- [x] **T3** — Lista + filtros + tarjetas + compartir + hooks.
- [x] **T4** — SEO + accesibilidad + empty states.
- [x] **T5** — Workflow GitHub Actions (pipeline best-effort + build + deploy Pages, cron 11:00 UTC).
- [x] **T6** — Tests + README + verificación local.

## Verificación

- `python3 -m pytest tests/ -q`
- `python3 build_site.py` — números observados (eventos incluidos, finde, archivos).

## Delivery

GitHub público (`cartelera-mdp`) + GitHub Pages. Commits por work unit. Sin PR.

## Presupuesto

Heurística ~600–900 líneas (generador + HTML/CSS/JS + tests).

## Evidencia / Progreso

- **T1/T2** (commit `29b79bb`): `build_site.py` + `site_assets/` (CSS, favicon) + `tests/test_build_site.py`. Regla de merge documentada en el docstring: sellers ganan título/precio/ticket/imagen, municipal gana la dirección, `dates` = unión de ocurrencias, gratis si algún miembro lo es. Quirk de datos: `events_deduped.json` solo trae clusters (41, 92 eventos), así que los singles (105) salen de `events_normalized.json` → 41 + 104 futuros = 145. Ventana jue–dom con tests de los 7 días (bug de fin de ventana el domingo detectado por el test y corregido).
- **T3** (commit `5448a1a`): filtros client-side en `app.js` (ventana/lugar/gratis) sobre el JSON inlineado, "Compartir" WhatsApp armado al click con `location` + datos de la tarjeta, `track()` stub con TODO de analítica, links con `data-outbound="ticket"` + `data-event-id`. Verificado corriendo el `app.js` real con un stub de DOM en Node: 145 → finde 27, 7 días 30, Club TRI 20, Club TRI+gratis 3, filtro sin resultados 0 + mensaje. `.card[hidden]` explícito para que `display:flex` no gane.
- **T4** (commits `29b79bb`+`5448a1a`): `<html lang="es">`, title/meta/og/canonical, JSON-LD (WebSite + ItemList con los 27 del finde), landmarks con `aria-labelledby`, skip link, foco visible, dark mode, empty states (finde vacío server-side; filtro vacío client-side), footer con atribución + "Actualizado: 13/10/2026 21:14".
- **T5** (commit `ba13958`): `.github/workflows/deploy.yml` — push a `main` + `workflow_dispatch` + cron `0 11 * * *` (08:00 ART); `contents: read`, `pages: write`, `id-token: write`; concurrency `pages`; build con pipeline best-effort (`continue-on-error: true`) → `build_site.py` → artifact `site`; deploy con environment `github-pages`. Sin push: el remoto lo maneja el parent.
- **T6** (commit de docs): 154 tests verdes (107 previos + 47 nuevos). `python3 build_site.py` → 145 eventos, 27 finde, 30 venues, 4 archivos. Build determinista `--today 2026-10-14` en `/tmp/opencode/site-check`. `python -m http.server -d site` sirve index/assets/favicon con 200. README con "Web local" y "Deploy".

## Cierre

- **Verificación independiente:** VERIFIED en sitio/datos/tests (build determinista — hashes idénticos en dos corridas; 145 próximos / 27 finde / 30 venues reproducidos; filtros y tests auditados; sin cambios fuera de alcance). **Hallazgo corregido:** pins de GitHub Actions desactualizados (era node20; majors vigentes verificados contra GitHub: checkout v7, setup-python v7, configure-pages v6, upload-pages-artifact v5, deploy-pages v5) → actualizados antes del primer deploy.
- **Deploy:** GitHub público `martinrdilo/cartelera-mdp` + Pages (`https://martinrdilo.github.io/cartelera-mdp/`), workflow con cron diario 11:00 UTC + push + dispatch; primer run disparado con el push de cierre.
