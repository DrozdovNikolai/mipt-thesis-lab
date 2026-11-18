# Additional sources: assumptions and checklist before experiments

2026-09-14. User requested further public data acquisition and actual improvement.
Previous requirements, releases, human reviews, inputs and all-sources-v1 outputs
remain unchanged. No external messages or purchases are authorized by this work.

- Acquire BLeRIOT-B v1 CC-BY-NC-4.0 noise and acoustic responses; verify publisher
  checksums, safe extraction and decode. Publisher noise descriptions do not become
  independent human verification. Assign each original noise source conservatively;
  never split its copies between train/dev/test. No test-reference hints.
- Acquire the open CVR Noort supplementary data. Inspect codebook and metadata
  before looking at text. Freeze source-case partition before training; keep the
  held-out text/labels in a separate curator-only path. Remove radio/ATC and unknown
  channel rows from any cockpit claim, using source metadata rather than inferred
  voice identities. Native safety-voice labels are human research labels, not the
  project's checklist/event ontology or temporal labels. Do not rename them to
  manufacture event/salience gate evidence. Compare a native-label classifier with
  a predeclared rule baseline, on disjoint cases, and report limitations.
- Investigate legal general RU controls independently of cabin quality. No source
  with unestablished rights or unknown recording origin is admitted as gold.
- Freeze a bounded follow-up ASR study before new hypotheses. Same parent model,
  precision and input language information for every pipeline. Existing models and
  baseline are not weakened. Preserve all results, including failures. At most four
  additional pipeline designs; no release promotion without all required gates.
- Test adapters/partition constraints, run real offline inference/training, compare
  immutable results and produce implemented/executed/verified reports and commands.
