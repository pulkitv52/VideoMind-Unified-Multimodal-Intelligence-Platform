# Roadscapes alternative to the Commons pack

Checked 18 October 2026. The Commons media host returned HTTP 429 during the
parent task's download attempts, so respect its Retry-After rather than retrying
through another route. Roadscapes is a separate publisher's dataset and a useful
alternative, not a mirror used to bypass that limit.

Publisher: [vijpandaturtle / Roadscapes Video Dataset](https://huggingface.co/datasets/vijpandaturtle/roadscapes-video).
The dataset card explicitly releases this collection under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), with attribution
for noncommercial research. Retain creator `vijpandaturtle`, dataset title,
publisher page, license link and revision in the local provenance manifest.
Do not reuse the author's companion code repository's MIT license as the media
license. Source-camera ownership and collection consent are not independently
documented in the card; this is publisher-asserted licensing, not an independent
rights audit.

The five pinned MP4 originals in [roadscapes-video-starter.json](roadscapes-video-starter.json)
are 18,006,975 bytes total (17.17 MiB); each is less than 6 MiB. They span three
day and two night sequences. Exact sizes and SHA-256 hashes are from the official
Hugging Face file tree/LFS metadata at revision
`be701e244d6d4a83b83723db4142463413484899`. A HEAD request to the first pinned
MP4 returned HTTP 200. Parent-task downloads must check their own full-file
hashes before reporting verification.

The manifest includes corresponding publisher CSV annotation rows, explicitly
tagged as Gemini 1.5 Pro output that the publisher says has not been manually
verified. Do not call them ground truth. Tentative scenarios from those rows are
traffic congestion, following a scooter on an urban road, a stopped junction,
wet nighttime traffic, and nighttime following. Inspect frames to confirm
observable descriptions before adding evaluation queries. Keep driving advice
fields out of evaluation answers: this project is testing evidence retrieval.

The publisher's recommended citation is `vijpandaturtle (2025), Roadscapes Video
Dataset, HuggingFace`, with the publisher page URL above. No account, credentials,
YouTube extraction, or complete dataset download is needed for the selected
files. These are demonstration inputs; no search accuracy is measured here.

The UZH RPG E2VID repository uses GPL for its source code, but neither its README
nor the linked driving-media page explicitly extends that license to externally
hosted media. Its research citation request alone was not treated as a clear
media license.
