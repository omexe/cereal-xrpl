PY=.venv/bin/python
.PHONY: setup pool preflight cosign vendor test demo export ledger-check
setup:        ## venv + deps
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
pool:         ## create/load roles → .env (run early: burners must age 256 ledgers)
	$(PY) scripts/setup_pool.py
preflight:    ## roles, balances, lock state, burn eligibility, vendor credentials
	$(PY) -m cereal.preflight
cosign:       ## the co-sign service on :8001
	.venv/bin/uvicorn cereal.cosign:app --port 8001 --reload
vendor:       ## vendor A's x402 endpoint on :8000
	$(PY) x402/server.py
test:         ## unit tests (no network)
	.venv/bin/pytest -q
demo:         ## scripted 90 seconds; needs cosign running and credentials issued
	$(PY) -m cereal.demo --sentence "Give the research agent 20 RLUSD for data vendors until tomorrow, project swell-brief, team growth, task news"
export:       ## accounting CSV
	$(PY) -c "from cereal.export import export_csv; from cereal.ledger import client; print(export_csv('exports/cereal-spend.csv', client()))"
ledger-check: ## Speculos signing preflight (needs the speculos-xrp container)
	cd ledger && npm run --silent speculos:check
