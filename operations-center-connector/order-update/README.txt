TPF Operations Center — Partner request / payment update (6 October 2026)

For the current 6 October Portal Update, with or without the Read-only Workspace Update.
Close Operations Center, extract this package, run INSTALL.bat and select your existing TPF_ADMIN folder.
The installer checks exact tested code hashes, backs up changed code, and never copies data or credentials.
A different code version stops before any change. Repeated installation is safe.

Partners → Online partner activity:
- Fetch new activity to import requests and selected offers.
- Cancel request closes an unpaid/test request and its online offer, preserving every pool and reward.
- Record verified payment requires the reviewed transaction hash and exact chosen Pi amount.
- Check the incoming wallet transaction and displayed request note yourself before recording payment.
- Connect verified pool and publish becomes available after payment is recorded and a suitable planted pool exists.
- Current order status is fetched from the online database on every page visit; it is not guessed from local event history.
- Read-only workspace shows the same payment details and progress as the partner.

OMC cleanup: cancel the old unpaid 20 Pi test request. Do not connect it to, recreate, or change OMC Welcome Pool.
No request is automatically cancelled by installation. No payment, planting, pool, invitation or reward is created.
Deploy previews show test-only payment instructions: do not send Pi for test offers.

Verification completed locally: isolated HTTP request/offer/choice/payment/pool flow; unpaid cancellation; duplicate payment rejection; partner isolation; payment gate; version-checked/idempotent installer; unchanged data sentinel; Admin rendering and signed cancellation; partner payment/copy/progress rendering.
Still to verify: installation in your running Windows Admin and actual signed-in online flow. Production OMC publication and global TPF addition 25% remain unconfirmed.
