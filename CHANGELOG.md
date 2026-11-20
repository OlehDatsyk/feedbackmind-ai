# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-20

### Added
- Authentication (registration, login, logout, refresh-token rotation with reuse detection, profile, password change).
- Workspaces with Owner / Administrator / Analyst / Viewer roles, invitations, member management and workspace switching.
- Overview dashboard, Feedback Hub, guided CSV / XLSX / JSON import with rejected-row reports.
- Rule-based baseline analysis (VADER sentiment, keyword topics and emotion cues) and optional AI analysis via Anthropic, OpenAI or Gemini with validated structured output.
- Topic management (custom, rename, merge, approve AI topics, keyword rules, TF-IDF suggestions) and aspect-level sentiment.
- Insights engine, trend analytics with significance tests, smart alerts, comparison workspace.
- AI Business Analyst with deterministic fact packs and validated citations.
- PDF, DOCX, XLSX and CSV reports generated in the background.
- REST API ingestion with API keys and HMAC-signed webhooks; catalogue of not-yet-implemented connectors with their requirements.
- PostgreSQL-backed durable job queue with embedded or standalone worker.
- Labelled, removable synthetic sample dataset.
- Docker Compose, Render Blueprint, GitHub Actions CI, Windows and macOS launchers.

### Fixed during the pre-release audit
- CSV rows with more fields than the header were silently reshaped by the parser (first column lost); such rows are now rejected and reported.
- Short non-UTF-8 files could be decoded with the wrong code page; decoding is now predictable (UTF-8 → Windows-1252 → detection) with an explicit encoding option.
- The first dashboard request could be sent without the workspace header.
- The AI Analyst page crashed in browsers where `scrollIntoView` returns a Promise.
- Horizontal overflow on narrow screens (dashboard cards, alert evidence links).
- Long imports could outlive their job lease; the lease is now renewed during processing.
- Oversized requests are rejected from `Content-Length` before the body is read.
- Very short texts (fewer than 3 words) are now marked *uncertain* by the rule-based analyser instead of being classified from a single word.
