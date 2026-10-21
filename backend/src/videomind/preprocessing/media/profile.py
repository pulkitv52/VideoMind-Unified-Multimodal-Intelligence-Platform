import hashlib
import json

CONFIG = {
    "version": "media-v1",
    "av": "16.1.0",
    "packages_snapshot": "debian-bookworm-20261018T000000Z",
    "asr_model": "Systran/faster-whisper-small.en",
    "asr_revision": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
    "faster_whisper": "1.2.1",
    "ctranslate2": "4.8.3",
    "asr_compute": "int8",
    "language": "en",
    "asr_vad": True,
    "asr_word_timestamps": True,
    "asr_beam": 1,
    "visual_fps": 1,
    "window_ms": 12000,
    "overlap_ms": 2000,
    "audio_window_ms": 20000,
    "shot_threshold": 0.35,
    "frame_width": 640,
    "playback_width": 960,
    "max_duration_ms": 300000,
    "max_decoded_frames": 36000,
    "max_pixels": 16000000,
    "max_output_bytes": 128 * 1024**2,
    "wall_seconds": 600,
}
PROFILE = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()

ASR_FILES = {
    "config.json": "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae",
    "model.bin": "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
    "tokenizer.json": "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
    "vocabulary.txt": "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf",
}
