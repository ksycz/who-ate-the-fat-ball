# Why close-up birds were missed (4 November 2026)

## Symptom

On 4 November, 26 visits were marked "Empty clip" with no bird guess at all. At least 5 of them clearly showed a great tit, and in each one the bird was:

- right against the lens,
- cut off at the edge of the picture, or
- half hidden behind the fat ball.

## Cause

The detector (MegaDetector v6) is trained on camera-trap photos of animals at a distance. A bird filling part of the frame gets a weak score. The matcher ignored every animal box under **0.3**, so the clip had nothing left to match and became "nothing".

What the detector stored for the 5 missed clips:

| Clip | Best animal box | Also |
|---|---|---|
| 701 | 0.23 | |
| 712 | 0.29 | |
| 727 | none | the bird was called a "person" (0.25) |
| 738 | none | the bird was called a "person" (0.15) |
| 768 | 0.15 | a 0.3 s clip, so only one frame was checked |

## How it was measured

A replay harness ran the real detector, feature print and matcher on the owner's 63 hand-labelled clips plus the 5 misses. It used the owner's own examples and left each clip's own examples out.

| Rule | Birds found (of 36) | Empty clips called a bird (of 17) |
|---|---|---|
| Cutoff 0.3 (before) | 28 | 1 |
| **Cutoff 0.2 (now)** | **31** | **1** |
| Cutoff 0.1 | 32 | 1, but more empty clips went to "Other" |
| Weak "person" boxes treated as animals | no better | worse |
| 6 frames a second instead of 2 | +1 bird | 6 instead of 3 empty clips were wrong |

So the cutoff is now **0.2**. A lower cutoff lets through more small boxes, and Vision refuses to describe a box that is too small to crop. Such a box is now skipped instead of failing the whole clip.

## Still missed

- Close birds the detector calls a "person" (727, 738).
- Very short clips (768).
- A clearly detected blue tit whose crop looked more like the owner's "nothing" examples (216).

These need a better detector or more examples from corrections (phase 3).

## Re-checking older visits

`uv run fatball recheck-empty` queues the clips of every empty visit for recognition again. Visits the owner moved are left alone. The running app works through them in the background.
