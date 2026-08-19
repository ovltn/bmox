# bmox project Makefile — filled in by /bmox:plan
STEP ?= $(shell python3 -c "import json;s=json.load(open('../.bmox/state.json'));p=s['projects']['{{TECH}}'];print(p.get('current_step') or 0)")

.PHONY: test grade
# /bmox:check reads this target's exit code as "reality answered", so it must
# fail whenever no implementation is passing — a target that only echoes reports
# green tests over an empty repo.
test:   ## run the current build step's tests
	{{TEST_CMD}}

grade:  ## run external grader if available
	@echo "wire the external tester here (e.g. codecrafters kafka-tester)"
