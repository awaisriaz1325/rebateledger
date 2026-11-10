# ADR 0004 — Chart library: Recharts

Status: accepted

Options: Recharts (React-native SVG, themeable via CSS variables, MIT, actively
maintained, 3.x), visx (low-level, more code), Chart.js (canvas — poorer screen
reader support), ECharts (large bundle).

Decision: **Recharts 3.x**, used sparingly (dashboard trends, tier tracker). Every
chart has a visible data table alternative and text summary for accessibility;
colours come from design tokens; no chart is the only carrier of a number.
