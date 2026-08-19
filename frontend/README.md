# Proteus Factory Home Frontend

This is an independent React + TypeScript + Vite + Tailwind frontend. It is not part of `hermes-runtime` and has no database, scheduler, worker, P6 runtime, raw SQL, authority command handler, or authority state mutation code.

## Adapter boundary

`src/models.ts` declares `ProductionDraftApi`, `ProductionPortfolioApi`, `GateApi` and `ProductionApi`. The default build uses the FH-1 `productApiAdapters`, which makes **GET-only** requests to `/factory-home/**` through typed adapter classes; React components do not call `fetch` directly. The development fixture is selected only when both Vite development mode and `VITE_PROTEUS_DEMO=true` are set. It carries a visible `DEVELOPMENT / DEMO` banner and never sends a command.

FH-1 currently consumes these read contracts when an approved backend composition is available: `GET /factory-home`, `GET /factory-home/productions`, `GET /factory-home/productions/{id}`, `GET /factory-home/gates`, `GET /factory-home/drafts`, and `GET /factory-home/status`. `progress`, worker/task counts, completion percentages, Factory telemetry and Draft data are never invented: they remain `NOT AVAILABLE` or `NOT IMPLEMENTED` unless a source-derived backend projection provides them. There are no POST/PATCH/PUT/DELETE frontend requests in FH-1.

## Product API development proxy

Vite proxies `/factory-home/**` to `VITE_PRODUCT_API_ORIGIN`, defaulting to `http://127.0.0.1:8000`. Set `VITE_PRODUCT_API_BASE_URL` only when the browser must call an approved same-origin or CORS-configured Product API directly. The browser must not provide a fake actor identity. The current backend bootstrap deliberately fails closed with `NOT_AVAILABLE` until an approved verified identity-to-Project-scope adapter is configured; untrusted actor headers are not production authorization.


## Run

```bash
pnpm install
pnpm dev
# Optional local visual fixture only:
VITE_PROTEUS_DEMO=true pnpm dev
```

The next backend task must provide authoritative Entry Draft, Portfolio, Gate list and Production Snapshot APIs. Replace only adapter implementations after those semantic contracts exist; do not put authority logic in React components.

## FH-1.x verified identity deployment

Factory Home production reads now require an OIDC bearer token at the Product API. The browser must send `Authorization: Bearer <token>` through the approved API deployment path; it must **not** use `X-Hermes-Actor-*` as authentication or choose Project IDs as authorization proof. The server validates the OIDC token and derives a conservative Project scope from the verified subject before querying the read model. A missing verifier configuration, invalid token, actor header mismatch or missing scope returns an explicit unavailable/authentication response rather than a global or fake Portfolio.

A production deployment must configure `HERMES_OIDC_ISSUER`, `HERMES_OIDC_AUDIENCE`, `HERMES_OIDC_JWKS_JSON`, and `HERMES_DATABASE_URL`. In their absence the Factory Home bootstrap remains fail-closed. React still performs no identity validation, Project authorization or localStorage actor scope handling.

## E1 EntryDraft Core

The browser now consumes the Product API’s creator-scoped EntryDraft contract through the existing `ProductionDraftApi` adapter. The supported routes are `POST /production-drafts`, `GET /production-drafts`, `GET /production-drafts/{id}`, `POST /production-drafts/{id}/revisions`, `POST /production-drafts/{id}/submit`, and `POST /production-drafts/{id}/archive`. All require the deployment’s verified OIDC bearer-token path; React neither verifies identity nor chooses a creator/project scope.

`/new` creates an **EntryDraft**, not a Project or Production. It navigates only after a server-returned Draft result. `/drafts` and `/drafts/:id` render only source-derived records available to the verified creator. A 409 version/idempotency response must be presented as a command conflict, never silently overwritten in local state. Missing/invalid authentication, unavailable authority and foreign Draft IDs remain API-driven unavailable/error states.

Development fixtures remain enabled only by `DEV + VITE_PROTEUS_DEMO=true`; all fixture Draft mutations intentionally return `NOT_IMPLEMENTED`. Production builds cannot choose fixtures.
