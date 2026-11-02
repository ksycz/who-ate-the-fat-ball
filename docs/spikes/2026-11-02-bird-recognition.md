# Spike: bird recognition (spec §13, spike 2)

**Date:** 2026-11-02 · **Decision:** detector + Apple Vision feature prints + the owner's own labelled examples ("my garden" matcher).

## Question

Which detector and classifier should name the visitors on the Mac, how accurate is it on real feeder clips, how fast is it, and is its licence compatible with MIT?

## Test set

- 63 real clips from the first week, labelled by hand and checked by the owner:
  - 31 with birds: 17 clearly identifiable (great tit, blue tit, house sparrow), 11 tits seen only from behind, plus a few unclear ones.
  - 32 without: the owner's two dogs (including a ginger shiba inu), people, and empty triggers (leaves under night infrared, sun glare, wind).
- Frames sampled at 2 per second (3,296 frames).
- Real footage stays private and is never committed. Only these results are.

## Hardware constraint found

The Mac is a MacBook Air with **8 GB of memory**. A 1.5–2 GB model (BioCLIP 2, ViT-L) caused heavy swapping and froze the Mac during batch tests. This is a hard requirement from now on:
- whatever runs all day must stay small (a few hundred MB),
- it runs at low priority, one clip at a time.

## Results

"Right section" means the clip landed in the spec's Birds, Other animals or Other. Species is counted on the 17 clearly identifiable birds.

| Setup | Right section (of 63) | Right species (of 17) | Owner's dogs | Cost | Licence |
|---|---|---|---|---|---|
| A. SpeciesNet (stopped at ~40%) | n/a | 0: every bird is just "bird" | black-and-white dog right; shiba "white-tailed deer" or "blank" | ~1 s/frame | Apache 2.0, but its detector pulls in AGPL `yolov5` |
| B. MegaDetector v6 MIT + BioCLIP 2 on crops | 50 (best rules) | 13 | called "cat" (up to 99% sure) | ~0.2 s/frame, 1.5–2 GB | MIT weights; the PytorchWildlife package pulls in AGPL `ultralytics`/`yolov5` |
| C. BioCLIP 2 on whole frames | 51 | 14 | shiba "red fox" or "empty" | ~3 s/frame on this Mac | MIT |
| **D. MegaDetector v6 MIT + Apple Vision feature print + nearest labelled examples** | **55** | **13** | **right** (shiba: "dog" or "nothing", both go to Other) | **18 ms per crop, 186 MB peak** | MIT weights + macOS built-in |

For D, each clip was judged only against examples from the *other* clips (leave-one-clip-out), with 5 nearest neighbours and a majority vote.

## Decision

Use **D**:
1. The **MegaDetector v6 MIT** (yolov9-c) detector finds animals and people.
2. Each animal crop gets an **Apple Vision feature print**.
3. The print is matched against a small library of the owner's labelled examples:
   - the birds that actually visit,
   - the two dogs (the owner confirmed only these two dogs are ever in the garden),
   - "nothing" (leaves, glare, arms).

Why:
- It is the most accurate on this feeder.
- It's the only setup that gets the dogs right.
- It's about 10 times lighter than the BioCLIP options.
- It has no licence problems.

What it means for the product:
- **The app only names species it has examples of.** A new species shows as "Unknown bird", and the owner names it once. From then on it's matched.
  - This brings part of the spec's phase 3 "learning from corrections" forward. Each correction adds an example.
  - The spike's labelled crops become the starting library.
- **Ruled out:**
  - BioCLIP 2: too heavy for this Mac.
  - SpeciesNet: no bird species, slow, AGPL detector dependency.
  - BirdNET (by sound): the models are CC BY-NC-SA, not MIT-compatible. The owner ruled it out.

## Thresholds and rules to carry into Plan 2

- Detector boxes count from confidence 0.3.
- If the detector sees a person in 2 or more frames, the clip is Other (person) whatever else it sees. The spike's two person clips that were mislabelled "great tit" would have been caught by this.
- A species needs a clear majority among the neighbours. Weak votes (about 0.6 or below) were behind most of the remaining wrong "great tit" calls on empty clips. The exact cut-off is set in Plan 2 against this test set.

## Known gaps

- **Blue tit vs great tit:** only 2–4 blue tit examples so far, so blue tits were called great tits. Expected to improve as examples are added.
- **Clips from before the feeder moved** (2026-10-28, a different camera angle): two birds there were called "dog". A camera move needs a few new examples.
- **Leakage:** clips from the same visit can sit on both sides of the leave-one-out split, so accuracy may be a little optimistic.
- **Detector package:** in the app, the MIT weights must be loaded without the PytorchWildlife package, which drags in AGPL code. Either use the MIT YOLO implementation directly, or export the detector to Core ML or ONNX. Plan 2 decides which.
- **Clock:** timestamps of clips recorded before the clock fix are about 7 hours ahead. Correcting old timestamps is a separate small task.

## Not yet measured

- ~~Detector speed without the PytorchWildlife wrapper.~~ Measured with the Core ML export (Task 1, M-series MacBook Air, run at `nice 19`): about 10 ms per 2560×1440 frame once warm (76 ms for the first call), against 0.14–0.21 s per frame on MPS in this spike. The Python process peaked at about 190 MB resident.
- Core ML export parity, on 9 spike frames from 3 clips. Against PyTorch in eval mode (CPU), the best animal box has the same class, IoU 0.96–1.00 and confidence within 0.08. Against the spike's own numbers it matches on clip 314 (IoU 0.84 and 0.95, confidence within 0.11) but not on clip 22: 0.51 against 0.33, IoU 0.27 on one frame. The cause is that PytorchWildlife leaves the YOLO-MIT model in training mode after loading, so the spike ran BatchNorm with per-image statistics. The Core ML model is the correct eval-mode network, which usually scores weak animals higher. The thresholds in this spike (`DET_MIN` and the rest) were tuned on the training-mode numbers, so Task 10 must re-check them on the Core ML detector.
- End-to-end time per clip, against the spec's 30-second target.
