import os
import tempfile
import streamlit as st
from faster_whisper import WhisperModel


@st.cache_resource(show_spinner="Loading Whisper STT model...")
def load_whisper_model():
    """Load the Faster-Whisper small.en model once and cache it for the session."""
    # 'small.en' is significantly more accurate than base (~244M parameters).
    # We use INT8 precision to keep it as fast as possible on CPU.
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    return model


def transcribe_audio_bytes(audio_bytes: bytes) -> str:
    """Transcribe raw audio bytes using Faster-Whisper.
    
    Supports WAV, WebM, OGG and most formats the browser may send.
    Returns the transcript as a string, or empty string on failure.
    """
    if not audio_bytes:
        return ""

    # Infer format from file header for correct ffmpeg decoding
    if audio_bytes[:4] == b'RIFF':
        ext = ".wav"
    elif audio_bytes[:4] == b'\x1aE\xdf\xa3':
        ext = ".webm"
    elif audio_bytes[:4] == b'OggS':
        ext = ".ogg"
    else:
        ext = ".webm"  # safe fallback — ffmpeg handles most containers

    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(audio_bytes)

        model = load_whisper_model()
        segments, _ = model.transcribe(tmp_path, beam_size=5)

        # The segments object is a lazy generator — must consume it before temp file is deleted
        transcript = " ".join([seg.text for seg in segments])
        return transcript.strip()

    except Exception as e:
        st.error(f"Failed to transcribe audio: {e}")
        return ""
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
