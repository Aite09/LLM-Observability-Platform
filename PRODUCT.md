# Product

## Register

product

## Users

Two audiences. Primary: AI/MLOps hiring managers and senior engineers reviewing a portfolio project — they skim fast, pattern-match against tools they run daily (Grafana, Datadog, Langfuse), and judge craft in seconds. Secondary: engineers self-hosting the platform to monitor their own LLM applications — they live in the dashboard during incident triage, often at night, on a second monitor, needing answers ("what regressed, what does it cost, is input drifting") in under a minute.

## Product Purpose

Self-hostable LLM evaluation and observability platform: logs every LLM call (cost, latency, tokens, traces), gates CI deploys on eval pass rates, detects input drift via embeddings, and visualizes all of it. Success = a reviewer concludes "a strong senior engineer built this" and a self-hoster trusts it during an incident.

## Brand Personality

Precise, calm, minimalist, well-engineered. Instrument-grade: the interface is a measuring device, not a brochure. Every pixel earns its place; data is the hero, chrome disappears. Confidence through restraint — nothing shouts, everything aligns.

## Anti-references

- Generic AI-generated dashboard: four identical KPI cards with icon + big number + green delta arrow, gradient accents, glassmorphism blur cards, purple-to-cyan gradients.
- Datadog/Grafana clone-with-a-theme: dense but characterless, default-library charts dropped in a grid.
- SaaS marketing gloss inside the app: hero metrics, decorative illustrations, empty whitespace theater.
- Bootstrap/admin-template energy: colored side-stripe cards, badge soup, rounded-blob everything.

## Design Principles

1. **Data is the interface.** Tables, numbers, and charts carry the design; decoration is subtracted, not added.
2. **Editorial density.** Dense like a well-set financial page — clear hierarchy through type scale, weight, and rules, not through boxes and color.
3. **One accent, spent deliberately.** A single accent color appears only where attention is genuinely required (alerts, gate failures, drift). If everything glows, nothing does.
4. **Motion states facts.** Animation only confirms state change (data refresh, chart draw-in, row insert) — never idles, never decorates.
5. **Instrument trust.** Monospace numerals, aligned decimal points, exact timestamps, honest empty/error states. The dashboard behaves like a calibrated tool.

## Accessibility & Inclusion

WCAG AA: ≥4.5:1 body text contrast, ≥3:1 large text, full keyboard navigation, visible focus states, `prefers-reduced-motion` honored on every animation, color never the sole carrier of meaning (severity always paired with text/icon).
