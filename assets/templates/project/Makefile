# bmox project Makefile — filled in by /bmox:plan
STATE := ../.bmox/state.json

# The step under test is the highest-numbered step that has actually been
# opened. state.json's `current_step` is null both while a step is still being
# set up and after `complete-step`, so reading that would aim `make test` at a
# step number nothing in the repo answers to — at exactly the two moments a
# learner runs it by hand. Skipped steps are excluded: nobody was asked to make
# their tests pass, so the last step that went green is the honest answer.
#
# Resolves to a step number, or to one of three words naming why there is none.
# A state file nothing can read and a project with nothing opened yet both leave
# the number empty, and only one of those is normal, so the reason has to reach
# the guard below. Every way of failing to read the record collapses onto
# `unreadable` — corrupt JSON, a schema this reader does not recognize, no
# python3 — because /bmox:status runs the state manager, which says which one it
# was far better than a Makefile can, and a Python traceback in front of the
# learner's test output teaches them to distrust this target.
#
# Every key below is indexed rather than defaulted, so a file whose shape this
# reader does not recognize raises instead of resolving a step number out of a
# record it only half understands.
STEP_STATE := $(shell python3 -c "import json,os;\
  p=json.load(open('$(STATE)'))['projects']['{{TECH}}'] if os.path.exists('$(STATE)') else None;\
  opened=[x['number'] for x in p['steps'].values() if x['phase']!='planned' and not x['skipped']] if p is not None else [];\
  print('absent' if p is None else max(opened,default='none'))" 2>/dev/null || echo unreadable)

# Empty rather than 0 when there is no step, because `go test ./... -run Step0`
# matches no test and exits 0, which is the vacuous green the `test` contract
# below exists to prevent.
STEP ?= $(filter-out absent none unreadable,$(STEP_STATE))

ifeq ($(STEP_STATE),absent)
STEP_HELP := no state file at $(STATE) — /bmox:plan writes it when it scaffolds a project, and it belongs in git
else ifeq ($(STEP_STATE),unreadable)
STEP_HELP := no readable record for {{TECH}} in $(STATE) — /bmox:status says why; this target stays red until it reads clean
else
STEP_HELP := no opened step in $(STATE) — run /bmox:step, or name one: make test STEP=1
endif

GRADER := {{GRADER}}

.PHONY: test grade
# /bmox:check reads these targets' exit codes as "reality answered", so they
# must fail whenever no implementation is passing — a target that only echoes
# reports green tests over an empty repo.
test:   ## run the current build step's tests
	@[ -n "$(STEP)" ] || { echo "$(STEP_HELP)"; exit 1; }
	{{TEST_CMD}}

# "no grader is wired here" and "the grader ran and the implementation is red"
# call for opposite next moves, so they have to be told apart — and make reports
# every recipe failure as its own exit status 2, which rules out doing that with
# a distinctive code. The wording below is the channel that survives, so
# /bmox:check reads it: keep the phrase intact if you reword the rest.
grade:  ## run the external grader
	@case "$(GRADER)" in ''|none) echo "no external grader is wired for {{TECH}} — nothing was graded"; exit 1 ;; esac
	$(GRADER)
