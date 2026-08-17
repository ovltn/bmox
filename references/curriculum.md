# Designing a bmox roadmap

A roadmap is good when every stage is (a) independently testable, (b) forces
one real design decision, and (c) sets up felt motivation for a later stage.
CodeCrafters-style staging works because pain precedes the cure: the learner
scans a log linearly in stage 3 so that the sparse index in stage 4 answers a
problem they have personally suffered.

## Research procedure (do this before drafting a single stage)

1. **Primary sources only.** Official protocol specs, design docs in the
   project's own repo, and the original papers. Blog summaries are for
   RESOURCES.md "further reading", never for roadmap facts.
   - Kafka: the protocol guide (kafka.apache.org/protocol), KIP documents.
   - Redis: the RESP spec, redis.io internals docs, antirez's design notes.
   - Generally: search "<tech> protocol specification", "<tech> design
     document", "<tech> architecture internals site:github.com".
2. **Find an external grader.** Check `github.com/codecrafters-io/<tech>-tester`
   first; then official conformance suites and test-vector sets. An external
   grader that cannot be sweet-talked is worth more than any prompt-level
   rule in this plugin. If one exists, wire it into the project Makefile
   (`make grade`) and anchor the roadmap's stage boundaries to its stages.
3. **Read the real project's directory layout** to learn the natural module
   seams (log/, network/, replication/). Stage boundaries should roughly
   follow real seams so the post-hoc comparison in review is meaningful.

## Interview the learner (3 questions, no more)

- Language for this project?
- Depth: toy (core data structures only) / realistic (single node, durable,
  correct) / distributed (replication, consensus)?
- What do they specifically want to understand? (This reorders stages —
  someone chasing "how does replication really work" should reach it by
  mid-roadmap, not stage 9.)

## Stage template — all three fields are mandatory

For each stage, the ROADMAP.md entry must name:

1. **Observable behavior** that proves it works (maps to a test).
2. **The design decision** the learner must make (if there is no decision,
   merge this stage into a neighbor — it is scaffolding, not learning).
3. **What the real system does here**, one sentence, for the later diff.

If you cannot fill all three, the stage is too vague: split or merge it.

## Structural rules

- 6–10 stages for realistic depth; 4–6 for toy; 10–14 for distributed.
- At least one stage is **deliberately naive** and says so in its brief, with
  a pointer to the stage that will fix it.
- Stage 1 is always end-to-end trivial (e.g. "TCP server answers one
  hardcoded request") so the learner has a running system on day one.
- Later stages may include an explicit "make it work, then measure" step;
  optimization belongs after green, never before.
