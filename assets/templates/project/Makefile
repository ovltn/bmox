# bmox project Makefile — filled in by /bmox:new
STAGE ?= $(shell python3 -c "import json;s=json.load(open('../.bmox/state.json'));p=s['projects']['{{TECH}}'];print(p.get('current_stage') or 0)")

.PHONY: test grade
test:   ## run current stage's tests
	@echo "wire your test runner here, e.g.: go test ./... -run Stage$(STAGE)"

grade:  ## run external grader if available
	@echo "wire the external tester here (e.g. codecrafters kafka-tester)"
