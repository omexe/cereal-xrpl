PY=.venv/bin/python
.PHONY: setup pool preflight service cosign vendor test acceptance demo main-agent beats retire export ledger-check
setup:        ## venv + deps
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
pool:         ## create/load roles → .env (run early: burners must age 256 ledgers)
	$(PY) scripts/setup_pool.py
preflight:    ## roles, balances, lock state, burn eligibility, vendor credentials
	$(PY) -m cereal.preflight
service:      ## the cereal service on :8001 (deploy, cosign, reclaim, retire)
	.venv/bin/uvicorn cereal.service:app --port 8001
cosign: service
vendor:       ## vendor A's x402 endpoint on :8000
	$(PY) x402/server.py
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
retire:       ## retire reclaimed subwallets (demo + test stores) once ≥256 ledgers old; returns the XRP reserve; safe to rerun
	@for f in deployments.json deployments.testnet.json deployments.testnet2.json; do \
	  [ -f $$f ] && echo "== $$f" && CEREAL_DEPLOYMENTS_FILE=$$f .venv/bin/python -m cereal.main_agent --retire-all; \
	done; true
