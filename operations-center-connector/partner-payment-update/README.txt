TPF Partner Payment Match Update — 2026-10-08

For the current Partner ID update version of Operations Center.
Close Operations Center, run INSTALL.bat and choose your existing TPF_ADMIN folder.
It checks the exact code version, backs up changed code, and replaces three code files.
No data, credentials, settings or pool records are replaced by installation.
This update needs no website deployment. It uses the existing production order API.

GPM payment flow
1. Restart Operations Center and refresh Wallet Watcher.
2. Select Partner Pool Payments for the 300 Pi payment. Confirm Classification
   takes you to online partner activity; it does not yet book funds or plant trees.
3. Fetch new activity if needed and find GPM's selected 300 Pi / 48 tree offer.
4. Select the incoming payment. Check its sender, date and hash.
5. Choose Manual match — missing or different memo.
6. Explain internally that GPM confirmed the sender and offer using its receipt.
7. Confirm sender/offer ownership and Record verified partner payment.
The app independently checks the successful mainnet transaction, native Pi,
configured recipient, exact amount and one incoming payment operation.
A matching memo is checked exactly when you select the memo method.
No missing memo is invented or written to the blockchain.

After success: the online order becomes planting_pending and one incoming entry
is booked to Partner Pool Payments. Local evidence includes original blockchain
memo, sender, recipient, amount, transaction/operation, matching explanation,
request, partner and confirmation time. It creates no regular donation pending file.
Then create the dedicated pool using the exact selected offer and correct partner
ownership. Verify actual planting proof before Connect verified pool and publish.
The partner order and fund entry represent fulfillment and accounting respectively;
do not also classify this same payment as a normal contribution or another fund.

If interrupted: revisit online activity and resume the same transaction. Evidence
is saved before the online call. Hash reuse, existing classifications, fund entries
and regular contribution records are blocked. The existing online exact-price and
unique transaction constraints remain in effect. Batch transactions with more
than one payment to configured TPF wallets require separate review and are rejected.
A stale payment lock after an unexpected process termination requires review;
close Admin and inspect payment-matches records before removing its lock file.

The paused homepage/data update package must be rebased onto this Admin version
before installation later. Do not install the earlier REVIEW package over this fix.
