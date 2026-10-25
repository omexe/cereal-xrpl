PY=.venv/bin/python
.PHONY: setup pool preflight service cosign vendor test acceptance demo main-agent beats device x402 shop vendor-test rails vendor-b vendor-c vendor-d vendor-e vendor-f ap4m-merchant retire export ledger-check
setup:        ## venv + deps
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
pool:         ## create/load roles → .env (run early: burners must age 256 ledgers)
	$(PY) scripts/setup_pool.py
preflight:    ## roles, balances, lock state, burn eligibility, vendor credentials
	$(PY) -m cereal.preflight
service:      ## the cereal service on :8001 (deploy, cosign, reclaim, retire)
	.venv/bin/uvicorn cereal.service:app --port 8001
cosign: service
vendor:       ## vendor A's paywall on :8000 (trusted): agenda 0.25, speakers 0.25 RLUSD
	X402_VENDOR="Vendor A" X402_ITEMS="agenda:0.25,speakers:0.25" $(PY) x402/server.py
vendor-b:     ## vendor B's paywall on :8002 (revoked, cheapest: the trap): agenda 0.05, speakers 0.05
	X402_PORT=8002 X402_VENDOR="Vendor B" X402_ITEMS="agenda:0.05,speakers:0.05" XRPL_PAY_TO=$$($(PY) -c 'from cereal import config; print(config.address("VENDOR_B"))') $(PY) x402/server.py
vendor-c:     ## vendor C's paywall on :8003 (trusted): agenda 0.15, speakers 0.30
	X402_PORT=8003 X402_VENDOR="Vendor C" X402_ITEMS="agenda:0.15,speakers:0.30" XRPL_PAY_TO=$$($(PY) -c 'from cereal import config; print(config.address("VENDOR_C"))') $(PY) x402/server.py
ap4m-merchant: ## the AP4M merchant on :4308 (XRPL EVM testnet; redeems vouchers, settles RLUSD to the payout wallet)
	cd ap4m && node merchant.mjs --port 4308 --price 0.25
test:         ## unit tests (no network)
	.venv/bin/pytest -q
acceptance:   ## Parts 1+2 acceptance on live testnet (~6 min, spends ~1.5 RLUSD to our own vendor accounts)
	.venv/bin/pytest -q -s --run-testnet -m testnet tests/
demo:         ## scripted 90 seconds; needs cosign running and credentials issued
	$(PY) -m cereal.demo --sentence "Give the research agent 20 RLUSD for data vendors until tomorrow, project swell-brief, team growth, task news"
export:       ## accounting CSV
	$(PY) -c "from cereal.export import export_csv; from cereal.ledger import client; print(export_csv('exports/cereal-spend.csv', client()))"
ledger-check: ## Speculos signing preflight (needs the speculos-xrp container)
	cd ledger && npm run --silent speculos:check
main-agent:   ## Part 1 demo: one goal → two subagents in two subwallets → reclaim
	$(PY) -m cereal.main_agent --goal "Pull the Swell agenda and speaker list from vendor A" --envelope 2 --subagents 2
beats:        ## Part 2 demo: revoked vendor refused with evidence, hijack stopped twice, stolen keys capped
	$(PY) -m cereal.main_agent --goal "Pull the Swell agenda and speaker list" --envelope 2 --subagents 2 --beats
x402:         ## Part 4 demo: subagents buy over x402 (needs make vendor; make vendor-b for the refusal)
	$(PY) -m cereal.main_agent --goal "Pull the Swell agenda and speaker list" --envelope 2 --subagents 2 --x402
shop:         ## Part 5 demo: quote all vendors, skip the revoked one, buy from the cheapest trusted, budget = quote + buffer
	$(PY) -m cereal.main_agent --goal "Pull the Swell agenda and speaker list" --envelope 2 --shop
vendor-test:  ## live proof of vendor lists and blacklisting: only-C wallet; pay C, A, B, unknown; blacklist C live; restore
	$(PY) -m cereal.vendortest
rails:        ## sidelined: x402 + Mastercard AP4M on one budget (needs the service started with CEREAL_AP4M=1)
	$(PY) -m cereal.main_agent --goal "Pull the Swell agenda and speaker list" --envelope 2 --subagents 2 --x402 --ap4m
device:       ## Part 3 demo: owner rejects a budget on the Ledger, approves two, recovers one subwallet alone
	$(PY) -m cereal.main_agent --goal "Pull the Swell agenda and speaker list" --envelope 2 --subagents 2 --device
retire:       ## retire reclaimed or recovered subwallets (demo + test stores) once ≥256 ledgers old; returns the XRP reserve; safe to rerun
	@for f in deployments.json deployments.testnet.json deployments.testnet2.json deployments.testnet3.json deployments.testnet4.json deployments.testnet5.json; do \
	  [ -f $$f ] && echo "== $$f" && CEREAL_DEPLOYMENTS_FILE=$$f .venv/bin/python -m cereal.main_agent --retire-all; \
	done; true

vendor-d:     ## Sites: Vendor D on :8004, honest x402 RLUSD site NOT credentialed by cereal (report 0.10); free pages, a USDC-only paywall
	X402_VENDOR="Vendor D" XRPL_PAY_TO=$$($(PY) -c 'from cereal import config; print(config.address("VENDOR_D"))') X402_ITEMS="report:0.10" X402_PREFIX=research X402_PORT=8004 $(PY) x402/server.py
vendor-e:     ## Sites: Vendor E on :8005, takes the payment and never delivers (report 0.10)
	X402_VENDOR="Vendor E" XRPL_PAY_TO=$$($(PY) -c 'from cereal import config; print(config.address("VENDOR_E"))') X402_ITEMS="report:0.10" X402_PREFIX=research X402_DELIVERY=fail X402_PORT=8005 $(PY) x402/server.py
vendor-f:     ## Sites: Vendor F on :8006, pays Vendor E but its xrp-ledger.toml lists Vendor D (payment redirected: blocked)
	X402_VENDOR="Vendor F" XRPL_PAY_TO=$$($(PY) -c 'from cereal import config; print(config.address("VENDOR_E"))') X402_TOML_ADDRESS=$$($(PY) -c 'from cereal import config; print(config.address("VENDOR_D"))') X402_ITEMS="report:0.10" X402_PREFIX=research X402_PORT=8006 $(PY) x402/server.py