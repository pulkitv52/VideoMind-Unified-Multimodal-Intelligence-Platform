# Phase 7 annotation review

These are provisional development labels, not adjudicated gold. Two independent human reviewers and disagreement resolution are required before release eligibility. Keep existing IDs and original SHA-256 values. Record reviewer identities, grades 0–3, exact intervals/regions and decisions in a separately versioned review file. Do not change `human_reviewed` or `adjudicated` based on an agent-only assessment.

| Family | Query examples | Expected files | Evidence basis |
|---|---|---|---|
| caviar-fight | two person fighting; Two people fighting; People fighting in an indoor lobby | caviar-Fight_Chase__derived.mp4 | publisher_frame_hypotheses |
| urfall-fall | A person falling to the floor; Someone loses balance and falls down; A person collapses indoors | urfall-fall-01__derived.mp4, urfall-fall-02__derived.mp4, urfall-fall-03__derived.mp4, urfall-fall-04__derived.mp4, urfall-fall-05__derived.mp4 | publisher_sequence_class_no_temporal_label |
| caviar-walk | A person walking through a lobby; People walking in an indoor entrance hall | caviar-Walk1__derived.mp4 | publisher_frame_hypotheses |
| roadscapes-driving | Driving along a road during the day; Dashcam footage of driving at night | roadscapes-day_11__derived.mp4, roadscapes-day_12__derived.mp4, roadscapes-day_13__derived.mp4, roadscapes-night_12__derived.mp4, roadscapes-night_13__derived.mp4 | sequence_name_only_requires_review |
| owned-safety | How do I safely open the electrical panel?; Switch off power before opening the safety panel | procedure.txt, scanned-page.pdf | publisher_sequence_or_owned_fixture |
| owned-speech | How do I safely open the electrical panel?; Turn off the power before opening the panel | spoken.mp4 | publisher_sequence_or_owned_fixture |
| owned-beeps | Repeated electronic beeping tones; A series of electronic beeps | beeps.wav | publisher_sequence_or_owned_fixture |
| public-cat | A close-up photograph of an orange cat; An orange cat looking at the camera | chelsea.png | publisher_sequence_or_owned_fixture |
| owned-square | A red square moving across a white background; A moving red square | silent.mp4, spoken.mp4 | publisher_sequence_or_owned_fixture |
| identifiers | caviar-Fight_Chase__derived.mp4; procedure.txt | caviar-Fight_Chase__derived.mp4, procedure.txt | publisher_sequence_or_owned_fixture |
| negative-1 | A submarine beneath Arctic ice | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |
| negative-2 | A giraffe eating leaves in the savanna | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |
| negative-3 | An astronaut repairing a satellite | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |
| negative-4 | A violinist performing on a concert stage | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |
| negative-5 | A volcano erupting beside a glacier | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |
| negative-6 | A recipe for strawberry cheesecake | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |
| negative-7 | person walking on roof | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |
| negative-8 | A helicopter rescuing a sailor | Proposed negative; absence requires review | agent_proposed_absence_requires_human_review |

CAVIAR temporal labels are mapped from publisher frame hypotheses through the retained frame/PTS mapping. UR Fall sequence names identify falls versus ADL; its synchronization CSV contains timestamps and accelerometer values, not fall interval labels. [Publisher format description](https://fenix.ur.edu.pl/mkepski/ds/uf.html). Roadscapes sequence hints and the proposed negative queries require independent review.

All variants of a family stay together. The UR Fall and Roadscapes families are diagnostic held-out families; they are not an independent gold test set.
