# Action and temporal review pack

Development observations only. These are agent proposals after seeing retrieval scores, not independent human gold. Four reserved sequences are excluded. Original media and source PTS are retained; contact sheets can miss motion between frames.

Use the [human worksheet](../../annotations/action-temporal-v1-review.md) for independent review. This command does not fill or adjudicate it. Boundary proposals describe the transition toward the floor through first settled floor posture; later lying is separate.

## Top-scored windows for `person falling`

IoU ranges express sensitivity to proposed boundary uncertainty, not a statistical confidence interval. Scores are similarities, not probabilities. Missing recipe/asset combinations were not encoded in that experiment.

| Recipe | Clip | Window (s) | Similarity | IoU range against agent proposal | Clears 0.70 |
|---|---|---|---:|---|---|
| current_native | caviar-Rest_FallOnFloor | 30.000–40.560 | 0.700353 | 0.000–0.000 | yes |
| current_native | urfall-fall-01 | 0.000–5.338 | 0.683024 | 0.150–0.250 | no |
| current_native | urfall-fall-02 | 0.000–3.670 | 0.673945 | 0.299–0.437 | no |
| current_native | urfall-fall-04 | 0.000–3.203 | 0.691237 | 0.417–0.584 | no |
| uniform12 | urfall-fall-01 | 0.000–5.338 | 0.683024 | 0.150–0.250 | no |
| uniform12 | urfall-fall-02 | 0.000–3.670 | 0.673945 | 0.299–0.437 | no |
| uniform12 | urfall-fall-04 | 0.000–3.203 | 0.691237 | 0.417–0.584 | no |
| short4 | urfall-fall-01 | 2.000–5.338 | 0.692042 | 0.240–0.400 | no |
| short4 | urfall-fall-02 | 0.000–3.670 | 0.673945 | 0.299–0.437 | no |
| short4 | urfall-fall-04 | 0.000–3.203 | 0.691237 | 0.417–0.584 | no |
| fine2 | urfall-fall-01 | 3.000–5.000 | 0.715216 | 0.401–0.635 | yes |
| fine2 | urfall-fall-02 | 2.000–3.670 | 0.695076 | 0.299–0.452 | no |
| fine2 | urfall-fall-04 | 1.000–3.000 | 0.714901 | 0.317–0.460 | yes |

## caviar-Fight_Chase

Two people move through lobby and approach/contact near left furniture around 11-14 s. Proximity/contact is visible; fighting intent and exact action boundaries remain unresolved.

[Open retained original](../../../.local/datasets/video30/derived/caviar-Fight_Chase__derived.mp4)

[Open timestamped frames](caviar-Fight_Chase.jpg)

![Source-PTS review frames](caviar-Fight_Chase.jpg)


## caviar-Rest_FallOnFloor

Person returns into view around 24 s, descends around 26-28 s, remains on floor until about 35 s, then rises. Current 30-40.56 s window starts after the proposed descent. Distant overhead view limits onset precision.

[Open retained original](../../../.local/datasets/video30/derived/caviar-Rest_FallOnFloor__derived.mp4)

Proposed onset range: [25920, 26400] ms; settled-floor range: [27840, 28320] ms. Human review pending.

[Open timestamped frames](caviar-Rest_FallOnFloor.jpg)

![Source-PTS review frames](caviar-Rest_FallOnFloor.jpg)

[Open timestamped frames](caviar-fall-transition.jpg)

![Source-PTS review frames](caviar-fall-transition.jpg)


## caviar-Rest_InChair

Indoor lobby with walking and a person resting near the furniture. Distant people and furniture occlusion prevent reliable chair-action boundaries from this sheet.

[Open retained original](../../../.local/datasets/video30/derived/caviar-Rest_InChair__derived.mp4)

[Open timestamped frames](caviar-Rest_InChair.jpg)

![Source-PTS review frames](caviar-Rest_InChair.jpg)


## caviar-Walk1

People traverse an indoor lobby; sampled frames support indoor walking context. No temporal walking labels assigned.

[Open retained original](../../../.local/datasets/video30/derived/caviar-Walk1__derived.mp4)

[Open timestamped frames](caviar-Walk1.jpg)

![Source-PTS review frames](caviar-Walk1.jpg)


## roadscapes-day_11

Road traffic and motorcyclists. Small distant figures cannot be confidently classified as walking pedestrians at sheet resolution.

[Open retained original](../../../.local/datasets/video30/derived/roadscapes-day_11__derived.mp4)

[Open timestamped frames](roadscapes-day_11.jpg)

![Source-PTS review frames](roadscapes-day_11.jpg)


## roadscapes-day_12

Road traffic, motorcyclists and roadside buildings. Pedestrian walking remains unknown at sheet resolution.

[Open retained original](../../../.local/datasets/video30/derived/roadscapes-day_12__derived.mp4)

[Open timestamped frames](roadscapes-day_12.jpg)

![Source-PTS review frames](roadscapes-day_12.jpg)


## roadscapes-day_13

Stopped road traffic and people on motorcycles/bicycles. Visible people alone do not establish walking.

[Open retained original](../../../.local/datasets/video30/derived/roadscapes-day_13__derived.mp4)

[Open timestamped frames](roadscapes-day_13.jpg)

![Source-PTS review frames](roadscapes-day_13.jpg)


## roadscapes-night_12

Night road traffic; glare and small subjects limit pedestrian visibility. Walking status unknown.

[Open retained original](../../../.local/datasets/video30/derived/roadscapes-night_12__derived.mp4)

[Open timestamped frames](roadscapes-night_12.jpg)

![Source-PTS review frames](roadscapes-night_12.jpg)


## roadscapes-night_13

Night road with truck and motorcycles; low light limits pedestrian visibility. Walking status unknown.

[Open retained original](../../../.local/datasets/video30/derived/roadscapes-night_13__derived.mp4)

[Open timestamped frames](roadscapes-night_13.jpg)

![Source-PTS review frames](roadscapes-night_13.jpg)


## urfall-adl-01

Walking then lowering into a sustained crouch. Sampled frames do not establish a fall; motion between samples remains unreviewed.

[Open retained original](../../../.local/datasets/video30/derived/urfall-adl-01__derived.mp4)

[Open timestamped frames](urfall-adl-01.jpg)

![Source-PTS review frames](urfall-adl-01.jpg)


## urfall-adl-02

Walking then lowering into a sustained crouch with hand near floor. A hard negative proposal for human review, not a confirmed absence label.

[Open retained original](../../../.local/datasets/video30/derived/urfall-adl-02__derived.mp4)

[Open timestamped frames](urfall-adl-02.jpg)

![Source-PTS review frames](urfall-adl-02.jpg)


## urfall-adl-24

Lowering toward a kneeling/crouched position and returning upright. No lateral floor posture in sampled frames; intent and fall absence are unadjudicated.

[Open retained original](../../../.local/datasets/video30/derived/urfall-adl-24__derived.mp4)

[Open timestamped frames](urfall-adl-24.jpg)

![Source-PTS review frames](urfall-adl-24.jpg)


## urfall-fall-01

Standing/walking, then rapid descent, roll and floor posture. Provisional fall transition; first floor settlement is uncertain during rolling.

[Open retained original](../../../.local/datasets/video30/derived/urfall-fall-01__derived.mp4)

Proposed onset range: [2936, 3203] ms; settled-floor range: [4004, 4271] ms. Human review pending.

[Open timestamped frames](urfall-fall-01.jpg)

![Source-PTS review frames](urfall-fall-01.jpg)


## urfall-fall-02

Initially seated/crouched near chair; forward descent, roll and floor posture. Onset from seated posture is ambiguous.

[Open retained original](../../../.local/datasets/video30/derived/urfall-fall-02__derived.mp4)

Proposed onset range: [1334, 1601] ms; settled-floor range: [2699, 2936] ms. Human review pending.

[Open timestamped frames](urfall-fall-02.jpg)

![Source-PTS review frames](urfall-fall-02.jpg)


## urfall-fall-04

Initially seated/crouched near chair; forward descent and roll to floor. The user identified this development example as relevant. Not independent gold.

[Open retained original](../../../.local/datasets/video30/derived/urfall-fall-04__derived.mp4)

Proposed onset range: [266, 533] ms; settled-floor range: [1868, 2135] ms. Human review pending.

[Open timestamped frames](urfall-fall-04.jpg)

![Source-PTS review frames](urfall-fall-04.jpg)
