---
name: skill-index
description: Index of available project skills and guidance for choosing which skill to read before using runtime tools.
version: 1.0.0
metadata:
  runtime:
    tags: [skills, discovery, routing, index]
    related_skills:
      - web-search-fallback
      - parallel-cli
      - korea-weather
      - srt-booking
      - joseon-sillok-search
      - library-book-search
      - household-waste-info
      - public-restroom-nearby
      - subway-lost-property
      - korean-character-count
      - mattermost-send
---

# Skill Index

Use this skill when deciding which project skill should be read for a user request.

This skill is a discovery guide. It does not replace the target skill. After choosing a likely skill, read that skill's `SKILL.md` before taking action.

## Categories

- `web`: Web search, scraping, domain intelligence, and academic paper search.
- `research`: Parallel command-line research and blog monitoring.
- `software-development`: Planning and subagent-driven development guidance.
- `mcp`: Native MCP integration.
- `messaging`: External messaging integrations.
- `k-skills`: Korean public data, Korean local information, Korean search surfaces, and Korean text utilities.

## Selection Guide

Read `web-search-fallback` when built-in web search is unavailable or DuckDuckGo search is specifically useful.

Read `web-scraping` when the user needs structured extraction from a webpage.

Read `academic-paper-search` when the user asks for papers, research literature, citations, or arXiv-style discovery.

Read `domain-intelligence` when the user asks about domain ownership, DNS, website technology, or web footprint.

Read `parallel-cli` when the task needs parallel command-line investigation.

Read `blogwatcher` when the user asks to monitor or summarize blog feeds.

Read `writing-plans` or `subagent-driven-development` for software planning and delegated development workflows.

Read `native-mcp` when the user asks about MCP tool or server integration.

Read `mattermost-send` when the user explicitly asks to send, share, post, or publish a message to Mattermost or a configured channel alias.

## Korean Skills

Read a skill under `k-skills` when the request is about Korean public data, Korean local information, Korean services, or Korean text utilities.

- `korea-weather`: Korean weather forecast by location or coordinates.
- `srt-booking`: SRT train availability, reservation inspection, booking, cancellation, and sold-out retry guidance through SRTrain.
- `fine-dust-location`: Korean fine dust and air quality by region.
- `han-river-water-level`: Han River water level by station.
- `seoul-subway-arrival`: Seoul subway real-time arrival information.
- `real-estate-search`: Korean real-estate region codes and public transaction lookup guidance.
- `zipcode-search`: Korean road-name address and postal code search.
- `geeknews-search`: GeekNews article listing and search.
- `korean-character-count`: Korean character count, byte count, and spacing-sensitive text metrics.
- `joseon-sillok-search`: Joseon Dynasty Annals keyword search using the official Sillok surface.
- `library-book-search`: Korean public library book search and holdings lookup through Data4Library proxy routes.
- `k-schoollunch-menu`: Korean school search and school meal menu lookup through NEIS proxy routes.
- `cheap-gas-nearby`: Nearby Korean gas station fuel price lookup through Opinet proxy routes.
- `lotto-results`: Korean Lotto draw result and ticket match lookup using the `k-lotto` package.
- `public-restroom-nearby`: Nearby Korean public/open restroom lookup using official public restroom data and optional Kakao location support.
- `subway-lost-property`: Conservative LOST112 and Seoul Metro lost-property lookup guidance for subway lost items.
- `household-waste-info`: Korean household waste disposal day, time, place, method, and contact lookup through data.go.kr proxy routes.

## Guardrails

Do not use a skill to perform login, booking, payment, account access, or external state-changing actions unless the target skill explicitly defines a safe approval flow.

For legal, medical, financial, tax, real-estate, or safety-sensitive topics, present results as informational and include source and time context when available.

If a skill depends on a proxy, API key, package, browser page, or script that is unavailable, do not guess. Explain the missing dependency and choose a safer fallback when possible.
