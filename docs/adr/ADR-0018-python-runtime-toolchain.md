# ADR-0018: Python 3.9+ for the First P0 Vertical Slice

Status: ACCEPTED  
Date: 2026-08-12  
Supersedes: None  
Superseded by: None  
Related specifications: [Runtime Spec §23](../specs/Hermes_Runtime_Normative_Spec_V1.0.md#23-recommended-first-vertical-slice)

## Context

The repository has no existing Runtime language toolchain. The available local interpreter is Python 3.9.6. The first slice needs immutable domain values, Command handlers, SQL adapters and executable tests, but no Web API.

## Decision

Implement the first P0 vertical slice in Python compatible with Python 3.9 and later. Domain and application layers use the standard library. Tests use `unittest`; no Web framework is introduced.

## Alternatives Considered

Require a newer Python version, Go or Rust; rejected for this slice because no repository evidence justifies the added bootstrap cost. FastAPI is unrelated to direct Command handler testing.

## Consequences

Code cannot rely on syntax or standard-library APIs introduced after Python 3.9. A later runtime-wide language/version decision may supersede this ADR.

## Validation

Compile and run all tests under the available Python 3.9 interpreter.

## Open Questions

Long-term supported Python versions, packaging and dependency management remain open.
