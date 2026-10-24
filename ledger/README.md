# ledger/ — the device leg (Node, because Ledger's DMK is TypeScript-only)

Signs the treasury's RLUSD funding `Payment` on a Ledger device or the Speculos emulator (the XRP app clear-signs IOU Payments). Batch, Credentials and AccountDelete stay software-signed in Python.

```bash
cd ledger && npm install
# Speculos (nanosp, XRP app) must be running on 127.0.0.1:5000; see the docker run line below
npm run speculos:check      # preflight: getAddress → sign a 1 XRP Payment → tesSUCCESS on testnet
```

Speculos container (one-time create, then `docker start speculos-xrp`), using the Ledger workshop ELFs:
`docker run -d --name speculos-xrp -p 127.0.0.1:5000:5000 -p 127.0.0.1:9999:9999 -p 127.0.0.1:41000:41000 -v "<path-to>/device-management-kit-ts-workshop/xrpl-hackathon/speculos/apps:/apps:ro" ghcr.io/ledgerhq/speculos:latest --model nanosp --display headless --api-port 5000 --apdu-port 9999 --vnc-port 41000 --vnc-password speculos --seed "$(cat .speculos-seed)" /apps/nanosp/app.elf`

`fund.ts` (step 2 of `docs/BUILD-ORDER.md`) reuses the connect → getAddress → sign → submit flow from `speculos-sign-check.ts` with the RLUSD amount, the job-tag memo and the SourceTag. `.speculos-seed` is gitignored; never use a real seed or real funds with Speculos.
