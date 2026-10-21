# CAVIAR: VideoMind local sample pack

For noncommercial local development. These clips are not a clinical or retrieval benchmark.

Uploaded MP4s are video-only resized derivatives, not upstream originals. Upstream files, annotations and per-frame source/time mappings are retained under `.local/datasets/video30/` on the host. The reproducibility manifest is `evaluation/manifests/video30.json`.

Conversion: PyAV/libx264, maximum width 640, CRF 23, source timing retained except explicit duplicate-PTS repairs. Original audio, if present, is retained only in the upstream file. No videos have been embedded or made searchable.

Includes shopping-centre and staged lobby scenes. Sequence names are selection hints; events have not been independently relabeled. Publisher XML is retained locally.

## caviar-OneLeaveShop1cor

- File: caviar-OneLeaveShop1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/OneLeaveShop1cor/OneLeaveShop1cor.mpg
- Original SHA-256: 283b4abe464feea871d06dee6fd7b2248dc6f967ce30cd89480d9603c00254a8
- Derivative SHA-256: d81607cec28e5ddb84aa6fe2e57acc1c8807042b78adc7e4933be62ee22c057d
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-OneLeaveShop1cor__derived.mapping.json
- Mapping SHA-256: 975b30e4eea552a912e0c49a20308939e668e11a08c71349337d83a3095311a8

## caviar-EnterExitCrossingPaths1cor

- File: caviar-EnterExitCrossingPaths1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/EnterExitCrossingPaths1cor/EnterExitCrossingPaths1cor.mpg
- Original SHA-256: f8363a5492e57787647c0e9e525b749a864e3bcbaee48a7353060525428a1367
- Derivative SHA-256: a1cbb22eec512cf1ca4015d42ab56268c89809b49b6d55746ae17ef6d7bac2bd
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-EnterExitCrossingPaths1cor__derived.mapping.json
- Mapping SHA-256: 46a94c1d79674a4fb11b1771ba67d544355212a5a80864d37c8bf87e8f5cbe80

## caviar-OneLeaveShopReenter1cor

- File: caviar-OneLeaveShopReenter1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/OneLeaveShopReenter1cor/OneLeaveShopReenter1cor.mpg
- Original SHA-256: 14d55141103159aedfaf9f2be798396536cdc00a4e5113f99063276181edf937
- Derivative SHA-256: 1be4e6b1208c23965455ad87d9308b71b32d496fb9255dd56dde632f7e25fdf8
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-OneLeaveShopReenter1cor__derived.mapping.json
- Mapping SHA-256: 8cbff553f27f674e5149a9671d91ce4167cfbe3a28caabd8362e310c7f7109fa

## caviar-OneShopOneWait1cor

- File: caviar-OneShopOneWait1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/OneShopOneWait1cor/OneShopOneWait1cor.mpg
- Original SHA-256: ffa3caf85910d40938755c6417c7ee123f746e2a101909132bb690c143099ff0
- Derivative SHA-256: ff98f36413b6c4c4b1394b7a1730c0d21073f2e52cf441bc6ec1d79911a0afa2
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-OneShopOneWait1cor__derived.mapping.json
- Mapping SHA-256: 65d809c8f2bfffd6e5f7292093f3327eb8ac4bd708fabd9b35eba13182a1df99

## caviar-OneStopEnter1cor

- File: caviar-OneStopEnter1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/OneStopEnter1cor/OneStopEnter1cor.mpg
- Original SHA-256: 05340115b48889f344f45c05593322b0c3cb9852081092226833f8e73d3ffb83
- Derivative SHA-256: 284e331ee9f60c555ce51ec4e7b30317ee37c214e22b84e1d0c3dde655cb7a1f
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-OneStopEnter1cor__derived.mapping.json
- Mapping SHA-256: dea9960b7a3d0c27ed6a4e393710235ecdfabd7e7ba68b185d267bbf406b0221

## caviar-ShopAssistant1cor

- File: caviar-ShopAssistant1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/ShopAssistant1cor/ShopAssistant1cor.mpg
- Original SHA-256: 504caed65c426688f1002426dbabdf9513ff78a6bfde6b971e6a6866198eba8a
- Derivative SHA-256: 69d69e27058f221baa40b7987210eb96fac0e7c1f5bad20ec5bcdfb4bfc2f75c
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-ShopAssistant1cor__derived.mapping.json
- Mapping SHA-256: 981842ccb0e20826652d736ed125523ee64e93c4da21c1ea1305804298a0110e

## caviar-OneStopMoveEnter1cor

- File: caviar-OneStopMoveEnter1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/OneStopMoveEnter1cor/OneStopMoveEnter1cor.mpg
- Original SHA-256: c9743f99f30002d7817fdfc10b599ef4b8ccb738477a00bae8e98175a98157ef
- Derivative SHA-256: 73d612f6eb86c2ee8dec6942b09a910710148f9a576f2846eccb55f556c5b6e2
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-OneStopMoveEnter1cor__derived.mapping.json
- Mapping SHA-256: 4ce6b810ee823504cfc24e51e7bc2f29b9bedac6bf99646a2c1b6dad499da64e

## caviar-Walk1

- File: caviar-Walk1__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/Walk1/Walk1.mpg
- Original SHA-256: a5d6dc7d7def01c1bdaeea8ff620195c148b366e1a52589bf4e46f15b6daa0c2
- Derivative SHA-256: 6f0d7edc011376f12a02c9b27cb393f33ac5e3bd14d992b5738e1dcf509d4f6c
- Duplicate-PTS frames adjusted by playback ticks: 2
- Frame mapping: .local/datasets/video30/derived/caviar-Walk1__derived.mapping.json
- Mapping SHA-256: b49897304fdee9dbc2d66a17bac8adc381de98235ecf28ae4f327c3e46325f42

## caviar-Browse1

- File: caviar-Browse1__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/Browse1/Browse1.mpg
- Original SHA-256: fafff382d83c7f091dc47396dee82159fb88c0d951b649b6f17afc2b0a914380
- Derivative SHA-256: ae6eb54e31cc218507283f745fc194f51794e37e94d32cc2c656f59c8ee29b4b
- Duplicate-PTS frames adjusted by playback ticks: 4
- Frame mapping: .local/datasets/video30/derived/caviar-Browse1__derived.mapping.json
- Mapping SHA-256: 0280a61cf3c9c822623548d36f0ae0c334d3eade4444e40c1fa85299b6d14813

## caviar-ThreePastShop1cor

- File: caviar-ThreePastShop1cor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA2/ThreePastShop1cor/ThreePastShop1cor.mpg
- Original SHA-256: 8a2aabaaf1b10234a1ab806006d37f78784c688bff809f661b7f0c617de02a88
- Derivative SHA-256: 2305dd62f10bae5452df2d0d6a60b82777c884938c310a106ea2a37baefb971a
- Duplicate-PTS frames adjusted by playback ticks: 0
- Frame mapping: .local/datasets/video30/derived/caviar-ThreePastShop1cor__derived.mapping.json
- Mapping SHA-256: b76b959fce7336dd86f4f93fa7c30161b125f93b958d014e8f4d052fe23a6562

## caviar-Rest_FallOnFloor

- File: caviar-Rest_FallOnFloor__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/Rest_FallOnFloor/Rest_FallOnFloor.mpg
- Original SHA-256: 06bc1d99e6766fd755adc215b3b5753f26d099f45c6578eee9c318e5c9637546
- Derivative SHA-256: a704c67a4057897066e133af1065a382fba43a2df3506c390d2816f2c5f476db
- Duplicate-PTS frames adjusted by playback ticks: 4
- Frame mapping: .local/datasets/video30/derived/caviar-Rest_FallOnFloor__derived.mapping.json
- Mapping SHA-256: 7828e66cacb7f5eb318c68a2d4d776aacc4cc0d4e6cdd4056ffeb54a8477564d

## caviar-LeftBag

- File: caviar-LeftBag__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/LeftBag/LeftBag.mpg
- Original SHA-256: 8f5d1dbf43d58da1bce57ca1b3f9491b8467773cfd66d2846f62f7d38d4a45e7
- Derivative SHA-256: ee002f556203a1ae70bfeeb10783b7d8923d08b24d49bcbd991c0843f5d60ed5
- Duplicate-PTS frames adjusted by playback ticks: 5
- Frame mapping: .local/datasets/video30/derived/caviar-LeftBag__derived.mapping.json
- Mapping SHA-256: efa244f05b57af16e84d0af2323fb7fe4c0b742b3afdfd3c6221644c910fb1d8

## caviar-Meet_WalkSplit

- File: caviar-Meet_WalkSplit__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/Meet_WalkSplit/Meet_WalkSplit.mpg
- Original SHA-256: 91a5b5c2a3060a02ebd1ee4264ab78ae7681e02d17d16c2546fcc7751c91805e
- Derivative SHA-256: 9ffe5db52e9efbb8276356a9084f6238dd7de88a24d5852a1e0616e6c67d0b4a
- Duplicate-PTS frames adjusted by playback ticks: 2
- Frame mapping: .local/datasets/video30/derived/caviar-Meet_WalkSplit__derived.mapping.json
- Mapping SHA-256: 399a97f4c430aacd5489e65f0a1f26ceaf7676acfe89a3bd7ebd8af0daa6c3fa

## caviar-Rest_InChair

- File: caviar-Rest_InChair__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/Rest_InChair/Rest_InChair.mpg
- Original SHA-256: 19b32edd0fe6ad0c0243f3c94adc787ffee28d8a74cb8ca73473fdfb996c423a
- Derivative SHA-256: 9d29de8e99514a9dd42f133d24ba2e9aa5204124d99d0b7f4a9f259d1bf21a2d
- Duplicate-PTS frames adjusted by playback ticks: 1
- Frame mapping: .local/datasets/video30/derived/caviar-Rest_InChair__derived.mapping.json
- Mapping SHA-256: 90bd30e6b3174088d2c214c3af0bec034d35a92ce4334cd173a48df53ec98eb9

## caviar-Fight_Chase

- File: caviar-Fight_Chase__derived.mp4
- Publisher: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/
- Credit: EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences
- License: CC BY-SA (publisher page does not identify version)
- Upstream: https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/Fight_Chase/Fight_Chase.mpg
- Original SHA-256: f8cd06377f1b5e821cf6f397bf8caf0f8173e82f988947fe90a4e33c059f8f4f
- Derivative SHA-256: 2c4361842a1a2130101171ff42ad5a911352f6b50816bf7e9d875cd2e4e40470
- Duplicate-PTS frames adjusted by playback ticks: 4
- Frame mapping: .local/datasets/video30/derived/caviar-Fight_Chase__derived.mapping.json
- Mapping SHA-256: fc9aa5e53226dee5b8a5753bdce97f7859e5409a7695c54aeceff6cd188613d0
