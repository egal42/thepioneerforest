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

It is not ready for production. Next: verify the complete flow on the isolated Netlify
preview with its real database, confirm the existing site's deploy configuration,
and check the current credit budget. Then package the Admin update without copying
over mainnet data. Run a GPM request/offer/choice and a verified pool/share flow in
the preview before publishing live.
No live credentials or mainnet data are kept in this repository.

Run the current unit tests with `npm test`.
