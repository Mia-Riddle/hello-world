"""
A small, dependency-light Whisper speech-to-text engine.

It runs the Whisper ONNX models published by the sherpa-onnx project
(https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models) with
onnxruntime, and decodes *with timestamps*, so every transcribed phrase
comes back with a start and end time. That is exactly what a lyric video
needs: one phrase per on-screen line.

You normally don't use this file directly - lyric_sync.py does.
"""

import base64
import os
import tarfile
import urllib.request
import zlib

import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 16000
N_FFT = 400
HOP = 160
CHUNK_SECONDS = 30
CHUNK_FRAMES = CHUNK_SECONDS * SAMPLE_RATE // HOP  # 3000 mel frames
SECONDS_PER_TIMESTAMP = 0.02

MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "asr-models/sherpa-onnx-whisper-{name}.tar.bz2")


# --------------------------------------------------------------------------
# Model download
# --------------------------------------------------------------------------
def ensure_model(name, models_dir):
    """Download + unpack a model the first time it's needed. Returns its folder."""
    folder = os.path.join(models_dir, f"sherpa-onnx-whisper-{name}")
    encoder = os.path.join(folder, f"{name}-encoder.int8.onnx")
    if os.path.exists(encoder):
        return folder
    os.makedirs(models_dir, exist_ok=True)
    archive = os.path.join(models_dir, f"{name}.tar.bz2")
    url = MODEL_URL.format(name=name)
    print(f"Downloading the '{name}' speech model (one time only, this can take a while)...")
    print(f"  {url}")

    shown = [-1]

    def progress(blocks, block_size, total):
        if total > 0:
            pct = min(100, blocks * block_size * 100 // total)
            if pct != shown[0]:
                shown[0] = pct
                print(f"\r  {pct}%", end="", flush=True)

    urllib.request.urlretrieve(url, archive, progress)
    print("\n  Unpacking...")
    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar.getmembers():
            # Only keep the small int8 models + tokens; skip the huge fp32 ones.
            base = os.path.basename(member.name)
            if base.endswith(".int8.onnx") or base.endswith("tokens.txt"):
                member.name = os.path.join(os.path.basename(folder), base)
                tar.extract(member, models_dir, filter="data")
    os.remove(archive)
    return folder


# --------------------------------------------------------------------------
# Audio loading + log-mel spectrogram (same maths as OpenAI's Whisper)
# --------------------------------------------------------------------------
def load_audio(path):
    """Decode any audio/video file (m4a, mp3, wav, mov...) to 16 kHz mono float32."""
    import av  # PyAV bundles its own ffmpeg, so no separate install is needed

    with av.open(path) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        pieces = []
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                pieces.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            pieces.append(out.to_ndarray().reshape(-1))
    return np.concatenate(pieces).astype(np.float32) / 32768.0


def _mel_filters(n_mels):
    """Slaney-style mel filterbank (identical to librosa.filters.mel defaults)."""
    def hz_to_mel(f):
        f = np.asarray(f, dtype=np.float64)
        mel = f / (200.0 / 3)
        log_region = f >= 1000.0
        return np.where(log_region, 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) / (np.log(6.4) / 27.0), mel)

    def mel_to_hz(m):
        m = np.asarray(m, dtype=np.float64)
        f = m * (200.0 / 3)
        log_region = m >= 15.0
        return np.where(log_region, 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0)), f)

    fft_freqs = np.linspace(0, SAMPLE_RATE / 2, N_FFT // 2 + 1)
    mel_pts = mel_to_hz(np.linspace(hz_to_mel(0), hz_to_mel(SAMPLE_RATE / 2), n_mels + 2))
    fdiff = np.diff(mel_pts)
    ramps = mel_pts[:, None] - fft_freqs[None, :]
    weights = np.zeros((n_mels, len(fft_freqs)))
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_pts[2:n_mels + 2] - mel_pts[:n_mels])
    return (weights * enorm[:, None]).astype(np.float32)


def log_mel(audio, n_mels):
    window = np.hanning(N_FFT + 1)[:-1].astype(np.float32)
    padded = np.pad(audio, (N_FFT // 2, N_FFT // 2), mode="reflect")
    n_frames = 1 + (len(padded) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spec = np.abs(np.fft.rfft(padded[idx] * window, axis=1)) ** 2
    spec = spec[:-1]  # Whisper drops the final frame
    mel = _mel_filters(n_mels) @ spec.T
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------
class Whisper:
    def __init__(self, folder, threads=None):
        name = os.path.basename(folder).replace("sherpa-onnx-whisper-", "")
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.encoder = ort.InferenceSession(os.path.join(folder, f"{name}-encoder.int8.onnx"), opts)
        self.decoder = ort.InferenceSession(os.path.join(folder, f"{name}-decoder.int8.onnx"), opts)

        meta = self.encoder.get_modelmeta().custom_metadata_map
        self.n_mels = int(meta["n_mels"])
        self.n_text_layer = int(meta["n_text_layer"])
        self.n_text_ctx = int(meta["n_text_ctx"])
        self.n_text_state = int(meta["n_text_state"])
        self.sot = int(meta["sot"])
        self.eot = int(meta["eot"])
        self.transcribe = int(meta["transcribe"])
        self.no_timestamps = int(meta["no_timestamps"])
        self.no_speech = int(meta["no_speech"])
        self.sot_prev = int(meta["sot_prev"])
        self.timestamp_begin = self.no_timestamps + 1
        self.is_multilingual = meta["is_multilingual"] == "1"
        self.lang_tokens = [int(x) for x in meta["all_language_tokens"].split(",") if x]
        self.lang_codes = [x for x in meta["all_language_codes"].split(",") if x]

        self.tokens = {}
        with open(os.path.join(folder, f"{name}-tokens.txt"), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2:
                    self.tokens[int(parts[1])] = base64.b64decode(parts[0])

        # Tokens Whisper should never emit while transcribing.
        self.suppress = [self.sot, self.sot_prev, self.transcribe, self.no_timestamps,
                         self.no_speech, int(meta["translate"]), int(meta["sot_lm"])]
        self.suppress += self.lang_tokens
        # Also block "[MUSIC]", "(", "♪" and friends: in a song Whisper would
        # otherwise happily label everything as music instead of writing words.
        self.suppress += [int(x) for x in meta.get("non_speech_tokens", "").split(",") if x]
        self.suppress = sorted(set(self.suppress))

    # -- low level ---------------------------------------------------------
    def _encode(self, mel_chunk):
        return self.encoder.run(None, {"mel": mel_chunk[None]})

    def _empty_cache(self):
        shape = (self.n_text_layer, 1, self.n_text_ctx, self.n_text_state)
        return [ort.OrtValue.ortvalue_from_numpy(np.zeros(shape, np.float32)) for _ in range(4)]

    def _start(self, cross_k, cross_v):
        """Fresh decoding state. The big key/value caches stay inside onnxruntime
        and are ping-ponged between two buffers, which is much faster than
        copying them in and out of Python on every word."""
        return {"caches": self._empty_cache(), "flip": 0,
                "cross_k": ort.OrtValue.ortvalue_from_numpy(cross_k),
                "cross_v": ort.OrtValue.ortvalue_from_numpy(cross_v)}

    def _step(self, state, tokens, offset):
        c = state["caches"]
        a, b = (0, 2) if state["flip"] == 0 else (2, 0)
        io = self.decoder.io_binding()
        io.bind_cpu_input("tokens", np.array([tokens], dtype=np.int64))
        io.bind_ortvalue_input("in_n_layer_self_k_cache", c[a])
        io.bind_ortvalue_input("in_n_layer_self_v_cache", c[a + 1])
        io.bind_ortvalue_input("n_layer_cross_k", state["cross_k"])
        io.bind_ortvalue_input("n_layer_cross_v", state["cross_v"])
        io.bind_cpu_input("offset", np.array([offset], dtype=np.int64))
        io.bind_output("logits")
        io.bind_ortvalue_output("out_n_layer_self_k_cache", c[b])
        io.bind_ortvalue_output("out_n_layer_self_v_cache", c[b + 1])
        self.decoder.run_with_iobinding(io)
        state["flip"] ^= 1
        return io.get_outputs()[0].numpy()[0, -1].astype(np.float64)

    def text(self, token_ids):
        raw = b"".join(self.tokens.get(t, b"") for t in token_ids if t < self.eot)
        return raw.decode("utf-8", errors="ignore")

    def encode_text(self, text):
        """Very small greedy BPE-ish encoder used only for the optional prompt."""
        lookup = {v: k for k, v in self.tokens.items() if k < self.eot}
        data = (" " + text.strip()).encode("utf-8")
        out, i = [], 0
        while i < len(data):
            for j in range(min(len(data), i + 24), i, -1):
                if data[i:j] in lookup:
                    out.append(lookup[data[i:j]])
                    i = j
                    break
            else:
                i += 1
        return out

    # -- language ----------------------------------------------------------
    def detect_language(self, mel_chunk):
        cross_k, cross_v = self._encode(mel_chunk)
        logits = self._step(self._start(cross_k, cross_v), [self.sot], 0)
        scores = logits[self.lang_tokens]
        best = int(np.argmax(scores))
        return self.lang_codes[best], self.lang_tokens[best]

    # -- decoding one 30 s window with timestamps ----------------------------
    def _decode_window(self, cross_k, cross_v, lang_token, prompt, max_ts_index):
        state = self._start(cross_k, cross_v)
        prefix = []
        if prompt:
            prefix = [self.sot_prev] + prompt[-(self.n_text_ctx // 2 - 1):]
        sot_seq = [self.sot] + ([lang_token, self.transcribe] if self.is_multilingual else [])
        initial = prefix + sot_seq

        logits = self._step(state, initial, 0)
        offset = len(initial)

        # Probability that this window has no speech at all (e.g. instrumental).
        first = self._step(self._start(cross_k, cross_v), [self.sot], 0)
        probs0 = np.exp(first - first.max())
        no_speech_prob = float(probs0[self.no_speech] / probs0.sum())

        out, logprob_sum = [], 0.0
        max_tokens = self.n_text_ctx // 2
        for _ in range(max_tokens):
            logits = logits.copy()
            logits[self.suppress] = -np.inf
            self._apply_timestamp_rules(logits, out, max_ts_index)
            logp = logits - np.logaddexp.reduce(logits[np.isfinite(logits)])
            token = int(np.argmax(logits))
            logprob_sum += float(logp[token])
            if token == self.eot:
                break
            out.append(token)
            if offset + 1 >= self.n_text_ctx:
                break
            logits = self._step(state, [token], offset)
            offset += 1
        avg_logprob = logprob_sum / max(1, len(out) + 1)
        return out, no_speech_prob, avg_logprob

    def _apply_timestamp_rules(self, logits, out, max_ts_index):
        tb = self.timestamp_begin
        # Timestamps beyond the real audio in this window are impossible.
        if tb + max_ts_index + 1 < len(logits):
            logits[tb + max_ts_index + 1:] = -np.inf
        last_was_ts = len(out) >= 1 and out[-1] >= tb
        penult_was_ts = len(out) < 2 or out[-2] >= tb
        if last_was_ts:
            if penult_was_ts:   # a pair just closed: next must be text
                logits[tb:] = -np.inf
            else:               # one open timestamp: next is timestamp or end
                logits[:self.eot] = -np.inf
        if not out:             # must begin with a timestamp near the start
            logits[:tb] = -np.inf
            logits[tb + 50 + 1:] = -np.inf
        ts_seen = [t for t in out if t >= tb]
        if ts_seen:             # timestamps never go backwards
            floor = ts_seen[-1] if (last_was_ts and not penult_was_ts) else ts_seen[-1] + 1
            logits[tb:floor] = -np.inf
        # If timestamps are collectively more likely than any text token, pick one.
        finite = np.isfinite(logits)
        if finite.any():
            logp = logits - np.logaddexp.reduce(logits[finite])
            ts_mass = np.logaddexp.reduce(logp[tb:][np.isfinite(logp[tb:])]) if np.isfinite(logp[tb:]).any() else -np.inf
            text_max = np.max(logp[:tb]) if np.isfinite(logp[:tb]).any() else -np.inf
            if ts_mass > text_max:
                logits[:tb] = -np.inf

    # -- whole song --------------------------------------------------------
    def transcribe_audio(self, audio, language=None, prompt_text=None, on_progress=None):
        """Returns (language_code, [ {start, end, text}, ... ])."""
        mel = log_mel(audio, self.n_mels)
        total = mel.shape[1]
        pad = np.zeros((self.n_mels, CHUNK_FRAMES), np.float32)
        mel = np.concatenate([mel, pad], axis=1)

        if language and language in self.lang_codes:
            lang_token = self.lang_tokens[self.lang_codes.index(language)]
        elif self.is_multilingual:
            # Detect from the middle of the song: intros are often instrumental.
            mid = max(0, min(total - CHUNK_FRAMES, total // 2 - CHUNK_FRAMES // 2))
            language, lang_token = self.detect_language(mel[:, mid:mid + CHUNK_FRAMES])
        else:
            language, lang_token = "en", None

        base_prompt = self.encode_text(prompt_text) if prompt_text else []
        segments, seek, history = [], 0, []
        while seek < total:
            window = mel[:, seek:seek + CHUNK_FRAMES]
            frames_left = min(CHUNK_FRAMES, total - seek)
            max_ts_index = int(frames_left * HOP / SAMPLE_RATE / SECONDS_PER_TIMESTAMP)
            cross_k, cross_v = self._encode(window)
            prompt = base_prompt + history[-120:]
            tokens, no_speech_prob, avg_logprob = self._decode_window(
                cross_k, cross_v, lang_token, prompt, max_ts_index)

            window_start = seek * HOP / SAMPLE_RATE
            window_segments, last_end_ts = self._split_segments(tokens, window_start)
            silent = no_speech_prob > 0.6 and avg_logprob < -1.0
            looping = _is_repetitive(" ".join(s["text"] for s in window_segments))
            if not silent and not looping:
                segments.extend(window_segments)
                history += [t for t in tokens if t < self.eot]
            else:
                history = []  # don't let a hallucination poison the next window

            # Move forward: to the last complete timestamp if we have one,
            # otherwise a full window.
            if last_end_ts is not None and last_end_ts > 1.0 and not silent:
                seek += int(round(last_end_ts * SAMPLE_RATE / HOP))
            else:
                seek += frames_left
            if on_progress:
                on_progress(min(seek, total) / total)
        return language, _merge_clean(segments)

    def _split_segments(self, tokens, window_start):
        tb = self.timestamp_begin
        segments, current, start = [], [], None
        last_end = None
        for t in tokens:
            if t >= tb:
                ts = (t - tb) * SECONDS_PER_TIMESTAMP
                if start is None:
                    start = ts
                else:
                    text = self.text(current).strip()
                    if text:
                        segments.append({"start": round(window_start + start, 2),
                                         "end": round(window_start + ts, 2),
                                         "text": text})
                    last_end = ts
                    start, current = None, []
            else:
                current.append(t)
        return segments, last_end


def _is_repetitive(text):
    """Whisper sometimes 'loops' on instrumentals. zlib makes that easy to spot."""
    data = text.encode("utf-8")
    if len(data) < 60:
        return False
    return len(data) / len(zlib.compress(data)) > 2.6


def _merge_clean(segments):
    cleaned = []
    for seg in segments:
        if seg["end"] <= seg["start"]:
            seg["end"] = seg["start"] + 1.0
        if cleaned and seg["text"] == cleaned[-1]["text"] and seg["start"] - cleaned[-1]["end"] < 0.5:
            cleaned[-1]["end"] = seg["end"]  # duplicated phrase across a window edge
            continue
        cleaned.append(seg)
    return cleaned
