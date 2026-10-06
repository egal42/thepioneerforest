# Live Partner Pool foundation

This branch is preparation, not a live Partner Pool. The existing site and fictional
`partner-pool-demo/` remain untouched. The branch deploy is a preview only.

The Operations Center is the source for partner identity, branding, verified planting,
pool ownership, and the fixed sharing basis. Its current `tpf_partner_public_setup_v1`
export is validated by `contract.mjs`. The export is setup data only: it contains no
share balances, partner credentials, requests, or live records.

Netlify Database is the planned online source for partner sessions, requests, and
immutable share records. The migration defines the tables. The API locks the pool
row, checks the share sum, and inserts a share and event in one transaction.
Local Operations Center sync uses event IDs and persists acknowledgements so
retries do not duplicate requests or shares. A pool must be published only after
payment and planting are verified locally with public proof.

The first authenticated API and partner workspace are present. A signed Operations
Center handoff, a local connector module, durable event inbox, and one-time account
invitation are implemented. A patch against the supplied Operations Center ZIP adds
Publish/Sync and an activity inbox. It has not been installed into the user's Windows
folder or tested against an actual Netlify Database.

The branch now includes the request/offer handoff, partner choice, sharing UI, and
a public pool/record page that appears only after local Admin activation. The Tree
and Planet share card uses partner colours with a readable dark fallback. The Admin
patch pulls online events every two minutes while Admin is open and catches up on
opening. The online ledger retains events while Admin is closed.

After a partner selects an offer, Admin can connect that request to a payment and
planting verified dedicated pool owned by the same partner. The selected choice
fixes the sharing basis and minimum promised units. Publication connects the pool
and request in one database transaction. A failed publication can be retried with
Publish / sync.

It is not ready for production. Next: verify the complete flow on the isolated Netlify
preview with its real database, confirm the existing site's deploy configuration,
and check the current credit budget. Package the Admin update without copying over
mainnet data. Run a GPM request/offer/choice and a verified pool/share flow against
the deployed preview before publishing live.
No live credentials or mainnet data are kept in this repository.

Run the current unit tests with `npm test`.

## Current preview handover — 6 October 2026

Continue from `live-partner-portal-foundation` / PR #1; do not replace main.
The isolated Netlify preview is `https://deploy-preview-1--thepioneerforest.netlify.app`.
OMC is published there with verified pool_006 (2 trees / 200 kg CO₂), zero shares
at this check, and public Tree-Nation proof. Public `/p/omc` is separate from the
Windows Admin's `/partners/omc/preview`, which always remains local.

The sandbox pool selector, selected-pool reward workspace, completed pools,
public pool/history routes, separate records list, and reward/card links are now
connected to the online authenticated API and ledger. The header logo sizing is
fixed. OMC pool_006 displays as OMC Welcome Pool without rewriting its stored
identifier or planting/ledger facts. Existing account, sessions, invitation,
requests, and pool data are preserved. The old pre-pool OMC introduction is
replaced for public display once pool_006 exists.

Verification: 17 backend tests passed; DOM fixture checks covered active and
completed selection, reward form limit, pool-specific history and all-record
navigation without writing real shares. Check the deployed public overview,
pool and records pages in a browser after deployment. Actual authenticated OMC
allocation and share-card download remain to be tested with the existing account.
No test reward, pool, planting or invitation was created. The user deferred gift
fund accounting and GPM until OMC is working. Global TPF addition must be 25%;
the running Windows setting is not accessible here, so restoration is unconfirmed.

### Follow-up verification and design consistency

A real-handler local HTTP integration test now runs with a fresh PostgreSQL-compatible
PGlite database and the repository migrations, replacing only Netlify platform adapters.
It covers publication, invitation activation/reuse rejection, login/logout, authenticated
shares, retries, overspending, fractional trees, partner isolation, public proof,
request/offer choice/verified-pool connection and durable Admin event retrieval.
This does not verify deployed database configuration, real authentication, concurrent
requests, or browser card downloads. Those remain online acceptance checks.
No preview sync secret or signed-in test account is available in this workspace;
do not bypass authentication or publish fictional planting as a verified online pool.

UI fixes: dark first-load defaults, full-viewport non-repeating background, consistent
left-aligned workspace/detail titles (centred public hero), grouped proof/card actions,
request form controls and submit button spacing, human request statuses, and
“Rewards shared with Pioneers” with “View record & share” action.

### Sandbox design restoration (6 October, follow-up)

The complete CSS string from `TPF_Partner_Integration_Test_v0_12_3/Partner_Portal/server.py`
is now ported as `sandbox-design.css`, with selector mappings documented at its top.
Online markup adapters preserve the stable non-repeating background, loading canvas,
form spacing and current authenticated workflow. Public pages use the sandbox's compact
header navigation, centred impact heading, totals note and icons, supporting colour,
accent borders, gradients and explanation steps. Private workspace uses its selector,
card, input and reward styling. `theme.js` reproduces the sandbox HLS supporting hue;
OMC defaults to colourful styling as in the source, other partners retain their profile
accent. No data is created or modified by this design port.

Public deployed pages can be visually checked. The authenticated private workspace
and populated online reward/share-card states still require a test session; the
isolated DOM checks do not replace that visual acceptance check.

### Read-only Operations Center workspace

`GET /api/ops/workspace?partnerId=...` uses the existing signed Operations Center
connection and exactly the same projection as `/api/partner/me`. It does not mint
sessions or expose credentials. The response is no-store and includes its retrieval
time. It has no POST/write action. The Windows update package adds a partner-detail
button and a local GET-only view with bundled Portal styles, disabled controls and
an explicit Admin banner. Every opening retrieves online data; errors never fall
back to local balances. Available offers do not establish that a partner has read
one. Requires installing `operations-center-connector/workspace-update` over the
6 October Portal Update; checksums stop on a different code version.
