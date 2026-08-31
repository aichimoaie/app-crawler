# App Crawler

An automation pipeline that drives a real Android app on a physical device, uses a vision-capable LLM to explore and describe its screens, and produces a Product Requirements Document (PRD) — per-screen use cases and a navigation flow graph — so a rebuild of the app can be planned and later handed to AI coding agents.

## Language

**Screen**:
One distinct state of the target app's UI, identified by a stable fingerprint of its UI hierarchy (not its screenshot pixels, which vary with dynamic content).
_Avoid_: Page, view, activity

**Fingerprint**:
A hash of a screen's normalized UI hierarchy, used to detect whether a screen has already been visited during a crawl.
_Avoid_: Hash, ID, signature

**Crawl**:
One run of the exploration loop, from app launch until the step cap is hit or the navigator model reports nothing new to explore.
_Avoid_: Session, run, scrape

**Navigator**:
The vision-LLM role that, given a screenshot and hierarchy of the current screen, produces a use case description and picks the next element to tap.
_Avoid_: Agent, planner, explorer

**Writer**:
The LLM role that assembles the accumulated per-screen data into the final Markdown PRD. May be the same underlying model as the Navigator, but is a distinct responsibility.
_Avoid_: Generator, summarizer

**Use Case**:
A short client-facing description of what a screen is for and what a user does on it, written by the Navigator and attached to that screen's entry in the flow graph.
_Avoid_: Description, summary

**Flow Graph**:
The complete map of Screens (nodes) and the taps that connect them (edges), built incrementally during a crawl and stored as `graph.json`.
_Avoid_: Sitemap, navigation tree

**Denylisted Action**:
A candidate tap the Navigator would be barred from executing because its element text/resource-id matches a blocked keyword pattern (e.g. financial actions). Not used in this project — see [ADR 0001](./docs/adr/0001-no-denylist-on-financial-actions.md).
_Avoid_: Blocked action, forbidden tap
