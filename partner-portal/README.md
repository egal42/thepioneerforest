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
