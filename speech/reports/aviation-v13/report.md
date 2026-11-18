# Full ATCOSIM comparison, v13

All **1901 clips / 122.74 minutes / 4 speakers** were scored. No omitted clips.

This is simulated controller speech with publisher transcripts. The published test partition was already used locally as development data; this is not a fresh held-out test. It does not replace cockpit evaluation. No training or threshold changes were made.

**Unmodified v11 failed on clip 7**, after six completed outputs: Canary reached its existing 256-token limit. The fourth row below is a separately declared variant that retains the v9 text on this failure. It encountered **5 generation-limit failures out of 1901 clips**; every failed generation is preserved and every clip is scored. Unmodified v11 has no full-corpus WER from the aborted batch. Successful decoding and consensus rules are unchanged. See `generation-guard-plan.json`.

| System | Lexical WER | Errors / words | Number-normalized WER |
|---|---:|---:|---:|
| Whisper small (previous run) | 69.66% | 15773 / 22642 | 50.82% |
| Whisper medium.en ATC (previous run) | 12.11% | 2741 / 22642 | 17.97% |
| Cockpit v9 (guarded v10 runtime) | 67.18% | 15212 / 22642 | 47.97% |
| v11 + generation-failure fallback to v9 | 57.34% | 12983 / 22642 | 45.69% |

Lower WER is better. Primary WER ignores ordinary punctuation/case; the secondary measure applies the same existing number normalization to references and hypotheses. It is not a correction of the transcripts.

The small and ATC predictions were reused from the hash-verified v1 execution (3802 records). Both cockpit profiles were run afresh on all inputs. The frozen checkpoint driver first had to reproduce the previous 16-clip end-to-end outputs; details are in `parity-verification.json`.

| Speaker | Clips | Small WER | ATC WER | v9 WER | v11 + fallback WER |
|---|---:|---:|---:|---:|---:|
| sm2 | 202 | 63.82% | 10.20% | 62.01% | 50.74% |
| zf1 | 641 | 71.00% | 11.29% | 68.48% | 54.77% |
| zf2 | 675 | 71.62% | 13.65% | 69.29% | 64.35% |
| zf3 | 383 | 66.68% | 11.49% | 63.78% | 52.10% |

v11 with the failure fallback changes the total lexical error count relative to v9 by **-2229** (-9.84 percentage points WER). Per-clip outcomes: `{'same_error_count': 1152, 'improved': 687, 'worsened': 62}`.

The failure handler reproduced all 16 stored successful outputs exactly, and a synthetic limit failure verified retaining the base text while continuing the batch. These replays made no new ASR calls. Six successful outputs from the aborted run were reused; one discarded failing generation was recomputed to capture it. The original aborted log and checkpoints are preserved.

These aggregate results cover only four speakers; they do not establish performance across all aviation speech. No automatic profile promotion was performed.

Cockpit results remain separate: [16 user-reviewed English clips](../cockpit-reviewed-v12/report.md). The extra [84 clips for manual review](http://localhost:8012/?split=dev) have machine drafts and no new human references from this run. The previous 42-clip queue and 16 reviewed references are preserved.

Validation: 15208 independent token-distance checks; exact coverage and checkpoint identities; frozen metric/runtime/input/reference hashes. See `verification.json` and `comparison.json`.
