# Partner order flow — 6 October 2026

Reference: latest supplied TPF_Partner_Integration_Test_v0_12_3/Partner_Portal/server.py, selected-offer payment screen and pool_request_agreements.

The newer implementation now shows the selected final Pi price, official TPF wallet and short request-specific memo (partner prefix + last 12 request UUID characters). Copy controls are private. Preview instructions explicitly prohibit test payments. Admin manually verifies the incoming transaction, amount and memo; this is not automatic chain matching or a Pi SDK checkout.

Transitions: new → offered → payment_pending → planting_pending → connected. Existing selected requests can receive payment verification. Unpaid new/offered/selected/payment_pending requests can be cancelled; paid/connected requests cannot be cancelled through this action. Cancellation withdraws online offers and hides them from partner active lists without deleting records. Existing connected requests are preserved on resync; no fabricated payment reference is added.

Signed /api/ops/order accepts cancellation or explicit payment confirmation. Exact decimal Pi amount must match the selected choice; unique 64-character transaction hash prevents reusing one payment for multiple orders. Pool publication with a new connection requires verified payment and sufficient verified backing. Direct gifted pools remain independent of purchase requests.

Local Admin order-update package supports the exact 6 October Portal Update before or after the Read-only Workspace Update. The installer preserves data/credentials and backs up changed code. Current online request state is fetched on each inbox visit. Live mutations require the user's existing Admin sync configuration; none were made to OMC during implementation.

Validated: 18 Node tests including actual handlers over isolated PGlite; 4 Python connector tests; payment/copy/progress DOM checks; existing public/private reward DOM checks; installer and Flask signed-action checks. Pending: actual Windows install, online authenticated acceptance, OMC test request cancellation, production URL verification and TPF addition setting confirmation.
