# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-14

### Documentation
- README (English and Korean): the real-sandbox example now passes `--agent-version` (or `SANDBOX_DRIFT_AGENT_VERSION`) so baselines record the agent version and FLIP reports show `agent_version: A -> B`.

## [0.1.0] - 2026-11-12

### Added
- `self`, `run` (`wrap`, `srt`, `replay` targets), `diff`, `init`, `fingerprint` and `convert` commands.
- Eight harmless canary probes: file writes inside and outside the work dir, a fake-HOME credential canary,
  a localhost listener, a proxy reserved-host request, a direct TEST-NET-1 connection, the docker socket
  and nested sandbox support.
- Expected-policy TOML (`block` / `allow` / `info`), snapshots, baseline comparison and `FLIP` detection.
- Exit codes: 0 matches, 1 mismatch or regression, 2 could not run.
- English and Korean output (`--lang`, `SANDBOX_DRIFT_LANG`, `LC_ALL`, `LC_MESSAGES`, `LANG`).
