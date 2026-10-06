# Changelog

All notable changes to this project are documented here. Versions follow SemVer.

## [Unreleased]

## [0.2.0] - 2026-10-06

### Added

- Explicit schema `2.0.0` generation and schema export with ten required platform blocks, including Pinterest title, complete description and hashtags.
- Partial Pinterest brief overrides, v2 brief validation and Pinterest block extraction.
- Version dispatch for metadata validation and extraction across both supported schemas.

### Changed

- Package version is `0.2.0`; default generation and schema export remain `1.0.0`, with the original v1 schema files and nine-platform contract preserved.
- Pinterest overrides require v2 generation; v1 rejects them instead of silently dropping editorial content. Publication limits remain the publisher's responsibility.

## [0.1.0] - 2026-10-06

### Added

- Python 3.12 CLI for deterministic metadata generation from one structured editorial brief.
- Nine-platform metadata envelope with local Draft 2020-12 schemas and strict validation.
- Schema export, platform extraction and optional import of flat YouTube metadata JSON.
- Examples and focused tests for generation, validation and publisher compatibility.
