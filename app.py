from __future__ import annotations

import math
import os
import re
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable

import av
import streamlit as st
from PIL import Image, ImageOps


APP_NAME = "AutoCine AI Video Editor"
MAX_UPLOAD_MB = int(os.getenv("AUTOCINE_MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
VIDEO_TYPES = ["mp4", "mov", "m4v", "mkv", "webm", "avi", "mpeg", "mpg", "ts"]
PRESETS: dict[str, tuple[int, int] | None] = {
	"Original size": None,
	"Vertical 9:16 - Reels / TikTok / Shorts": (1080, 1920),
	"Square 1:1 - Social feed": (1080, 1080),
	"Widescreen 16:9 - YouTube": (1920, 1080),
}


def get_duration(container: av.container.InputContainer) -> float | None:
	if container.duration is not None:
		duration = container.duration / av.time_base
		return duration if duration > 0 else None

	durations = [
		float(stream.duration * stream.time_base)
		for stream in container.streams
		if stream.duration is not None and stream.time_base is not None
	]
	return max(durations) if durations else None


def inspect_video(path: Path) -> dict[str, object]:
	try:
		with av.open(str(path), mode="r") as container:
			video_stream = next(iter(container.streams.video), None)
			if video_stream is None:
				raise ValueError("இந்தக் கோப்பில் வீடியோ stream இல்லை.")
			duration = get_duration(container)
			if duration is None:
				raise ValueError("இந்த வீடியோவின் கால அளவைப் படிக்க முடியவில்லை.")
			return {
				"duration": duration,
				"width": video_stream.codec_context.width,
				"height": video_stream.codec_context.height,
				"has_audio": next(iter(container.streams.audio), None) is not None,
			}
	except (av.error.FFmpegError, OSError) as error:
		raise ValueError(
			"இந்தக் கோப்பைத் திறக்க முடியவில்லை. ஆதரிக்கப்படும் MP4, MOV, MKV, "
			"WebM அல்லது AVI வீடியோவைத் தேர்ந்தெடுக்கவும்."
		) from error


def _frame_seconds(frame: av.frame.Frame, fallback: float) -> float:
	if frame.pts is None or frame.time_base is None:
		return fallback
	return float(frame.pts * frame.time_base)


def _mux_audio_frame(
	frame: av.AudioFrame,
	output_stream: av.audio.stream.AudioStream,
	start_seconds: float,
	end_seconds: float,
) -> int:
	sample_rate = frame.sample_rate or 44_100
	frame_start = _frame_seconds(frame, 0.0)
	first_sample = max(0, math.ceil((start_seconds - frame_start) * sample_rate))
	last_sample = min(frame.samples, math.floor((end_seconds - frame_start) * sample_rate))
	if first_sample >= last_sample:
		return 0

	samples = frame.to_ndarray()[:, first_sample:last_sample]
	clipped = av.AudioFrame.from_ndarray(samples, format="fltp", layout="stereo")
	clipped.sample_rate = sample_rate
	clipped.pts = max(0, round((frame_start + first_sample / sample_rate - start_seconds) * sample_rate))
	clipped.time_base = Fraction(1, sample_rate)
	for packet in output_stream.encode(clipped):
		output_stream.container.mux(packet)
	return last_sample - first_sample


def render_edit(
	source_path: Path,
	output_path: Path,
	start_seconds: float,
	end_seconds: float,
	target_size: tuple[int, int] | None,
	extract_audio: bool,
	progress: Callable[[float], None],
) -> None:
	with av.open(str(source_path), mode="r") as source:
		video_input = next(iter(source.streams.video), None)
		audio_input = next(iter(source.streams.audio), None)
		if video_input is None:
			raise ValueError("இந்தக் கோப்பில் வீடியோ stream இல்லை.")
		if extract_audio and audio_input is None:
			raise ValueError("இந்த வீடியோவில் பிரித்தெடுக்கக்கூடிய audio இல்லை.")

		video_output = None
		audio_output = None
		audio_resampler = None
		if not extract_audio:
			rate = video_input.average_rate or video_input.base_rate or Fraction(30, 1)
			rate = Fraction(rate).limit_denominator(120)
			if rate <= 0:
				rate = Fraction(30, 1)
			width = target_size[0] if target_size else max(2, video_input.codec_context.width // 2 * 2)
			height = target_size[1] if target_size else max(2, video_input.codec_context.height // 2 * 2)

		streams = [audio_input] if extract_audio else [video_input]
		if not extract_audio and audio_input is not None:
			streams.append(audio_input)

		with av.open(str(output_path), mode="w") as output:
			if not extract_audio:
				video_output = output.add_stream("libx264", rate=rate)
				video_output.width = width
				video_output.height = height
				video_output.pix_fmt = "yuv420p"
				video_output.options = {"preset": "veryfast", "crf": "23"}
			if audio_input is not None:
				audio_output = output.add_stream("aac", rate=44_100)
				audio_output.layout = "stereo"
				audio_resampler = av.AudioResampler(format="fltp", layout="stereo", rate=44_100)

			video_frames = 0
			audio_samples = 0
			last_video_pts = -1
			video_fallback = 0.0
			audio_fallback = 0.0
			last_progress_at = 0.0

			def update_progress(timestamp: float) -> None:
				nonlocal last_progress_at
				now = time.monotonic()
				if now - last_progress_at >= 0.15:
					fraction = (timestamp - start_seconds) / (end_seconds - start_seconds)
					progress(min(0.94, max(0.02, fraction * 0.94)))
					last_progress_at = now

			for packet in source.demux(*streams):
				for decoded in packet.decode():
					if isinstance(decoded, av.VideoFrame) and video_output is not None:
						timestamp = _frame_seconds(decoded, video_fallback)
						video_fallback = timestamp + 1 / float(rate)
						if timestamp < start_seconds or timestamp >= end_seconds:
							continue

						image = decoded.to_image()
						if image.size != (width, height):
							image = ImageOps.fit(
								image,
								(width, height),
								method=Image.Resampling.LANCZOS,
							)
						encoded_frame = av.VideoFrame.from_image(image)
						pts = max(last_video_pts + 1, round((timestamp - start_seconds) * float(rate)))
						encoded_frame.pts = pts
						encoded_frame.time_base = Fraction(rate.denominator, rate.numerator)
						last_video_pts = pts
						video_frames += 1
						for encoded_packet in video_output.encode(encoded_frame):
							output.mux(encoded_packet)
						update_progress(timestamp)

					elif isinstance(decoded, av.AudioFrame) and audio_output is not None:
						resampled_frames = audio_resampler.resample(decoded)
						for resampled in resampled_frames:
							timestamp = _frame_seconds(resampled, audio_fallback)
							audio_fallback = timestamp + resampled.samples / resampled.sample_rate
							audio_samples += _mux_audio_frame(
								resampled,
								audio_output,
								start_seconds,
								end_seconds,
							)
							update_progress(timestamp)

			if audio_resampler is not None and audio_output is not None:
				for resampled in audio_resampler.resample(None):
					audio_samples += _mux_audio_frame(
						resampled,
						audio_output,
						start_seconds,
						end_seconds,
					)
			if video_output is not None:
				for packet in video_output.encode(None):
					output.mux(packet)
			if audio_output is not None:
				for packet in audio_output.encode(None):
					output.mux(packet)

			if not extract_audio and video_frames == 0:
				raise ValueError("இந்த trim வரம்பில் வீடியோ frame இல்லை. வேறு நேரத்தைத் தேர்ந்தெடுக்கவும்.")
			if extract_audio and audio_samples == 0:
				raise ValueError("தேர்ந்தெடுத்த நேரத்தில் audio இல்லை.")
			progress(1.0)


def format_time(seconds: float) -> str:
	whole_seconds = int(seconds)
	hours, remainder = divmod(whole_seconds, 3600)
	minutes, seconds_part = divmod(remainder, 60)
	hundredths = int((seconds - whole_seconds) * 100)
	return f"{hours:02}:{minutes:02}:{seconds_part:02}.{hundredths:02}"


def safe_stem(filename: str) -> str:
	stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip(".-")
	return stem or "autocine-edit"


st.set_page_config(page_title=APP_NAME, page_icon="A", layout="wide")
st.markdown(
	"""
	<style>
	:root {
	  color-scheme: dark;
	  --canvas: #0c100e;
	  --panel: #151b17;
	  --line: #2a342d;
	  --text: #edf2e9;
	  --muted: #9da99f;
	  --lime: #c6f36b;
	}
	.stApp { background: var(--canvas); color: var(--text); }
	[data-testid="stHeader"] { background: transparent; }
	[data-testid="stAppViewContainer"] > .main { background: var(--canvas); }
	[data-testid="stMainBlockContainer"] { max-width: 1180px; padding-top: 2rem; }
	[data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"] { color: var(--muted); }
	h1, h2, h3 { color: var(--text); letter-spacing: 0; }
	.eyebrow { color: var(--lime); font-size: .75rem; font-weight: 700; letter-spacing: .08em; }
	.subtle-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 1rem; }
	.stButton > button[kind="primary"] { background: var(--lime); border-color: var(--lime); color: #141a12; font-weight: 700; }
	.stButton > button { border-radius: 6px; min-height: 2.8rem; }
	[data-testid="stFileUploader"] section { background: var(--panel); border: 1px dashed #465347; border-radius: 8px; }
	[data-testid="stMetric"] { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: .8rem; }
	[data-testid="stDownloadButton"] button { border-color: var(--lime); }
	</style>
	""",
	unsafe_allow_html=True,
)

st.markdown('<div class="eyebrow">VIDEO WORKSPACE / வீடியோ திருத்தி</div>', unsafe_allow_html=True)
st.title(APP_NAME)
st.caption("Trim, resize, preview, and export your video. / வீடியோவை வெட்டி, அளவு மாற்றி, பதிவிறக்கவும்.")

uploaded_file = st.file_uploader(
	"Upload a video / வீடியோவைப் பதிவேற்றவும்",
	type=VIDEO_TYPES,
	help=f"MP4, MOV, MKV, WebM, AVI and more. Maximum size: {MAX_UPLOAD_MB} MB.",
)

if uploaded_file is None:
	st.info("தொடங்க, மேலே ஒரு வீடியோவைத் தேர்ந்தெடுக்கவும். உங்கள் கோப்பு {0} MB-ஐ விடச் சிறியதாக இருக்க வேண்டும்.".format(MAX_UPLOAD_MB))
	with st.expander("AI editing / AI திருத்தம்"):
		st.write("AI editing is not enabled in this MVP. No AI service or API key is required; trimming, resizing, and audio export use video-processing tools only.")
else:
	signature = (uploaded_file.name, uploaded_file.size)
	if st.session_state.get("source_signature") != signature:
		st.session_state["source_signature"] = signature
		st.session_state["processed_result"] = None

	if uploaded_file.size > MAX_UPLOAD_BYTES:
		st.error(f"இந்தக் கோப்பு {MAX_UPLOAD_MB} MB வரம்பைத் தாண்டுகிறது. சிறிய வீடியோவைத் தேர்ந்தெடுக்கவும்.")
	else:
		st.markdown("#### Source / மூல வீடியோ")
		left, right = st.columns([1.35, 0.9], gap="large")
		with tempfile.TemporaryDirectory(prefix="autocine-") as temporary_directory:
			source_path = Path(temporary_directory) / Path(uploaded_file.name).name
			with source_path.open("wb") as source_file:
				source_file.write(uploaded_file.getbuffer())

			try:
				metadata = inspect_video(source_path)
			except ValueError as error:
				st.error(str(error))
				metadata = None

			if metadata is not None:
				duration = float(metadata["duration"])
				with left:
					st.video(uploaded_file.getvalue())
				with right:
					st.markdown('<div class="subtle-panel">', unsafe_allow_html=True)
					st.markdown(f"**{uploaded_file.name}**")
					st.metric("Duration / கால அளவு", format_time(duration))
					st.metric("Resolution / தெளிவுத்திறன்", f"{metadata['width']} x {metadata['height']}")
					st.caption("Audio track: available / உள்ளது" if metadata["has_audio"] else "Audio track: none / இல்லை")
					st.markdown("</div>", unsafe_allow_html=True)

				st.markdown("#### Edit / திருத்தம்")
				step = max(0.01, min(0.5, duration / 100))
				trim_range = st.slider(
					"Trim range / வெட்ட வேண்டிய நேரம்",
					min_value=0.0,
					max_value=duration,
					value=(0.0, duration),
					step=step,
					format="%.2f s",
				)
				setting_col, audio_col = st.columns([1.3, 1])
				with setting_col:
					preset_name = st.selectbox("Output size / வெளியீட்டு அளவு", list(PRESETS))
				with audio_col:
					extract_audio = st.checkbox(
						"Extract audio only / audio மட்டும்",
						help="Exports the selected audio as an AAC M4A file.",
					)

				if trim_range[1] <= trim_range[0]:
					st.warning("End time must be after start time. / முடிவு நேரம் தொடக்க நேரத்திற்குப் பிறகு இருக்க வேண்டும்.")
				else:
					process_clicked = st.button(
						"Extract audio / audio எடுக்கவும்" if extract_audio else "Process video / வீடியோவை உருவாக்கவும்",
						type="primary",
						use_container_width=True,
						disabled=extract_audio and not metadata["has_audio"],
					)
					if process_clicked:
						result_progress = st.progress(0, text="Preparing your edit...")
						result_name = f"{safe_stem(uploaded_file.name)}-edited.{ 'm4a' if extract_audio else 'mp4' }"
						output_path = Path(temporary_directory) / result_name
						try:
							render_edit(
								source_path=source_path,
								output_path=output_path,
								start_seconds=float(trim_range[0]),
								end_seconds=float(trim_range[1]),
								target_size=None if extract_audio else PRESETS[preset_name],
								extract_audio=extract_audio,
								progress=lambda value: result_progress.progress(
									value,
									text="Processing video... / வீடியோவை உருவாக்குகிறது...",
								),
							)
							st.session_state["processed_result"] = {
								"name": result_name,
								"data": output_path.read_bytes(),
								"mime": "audio/mp4" if extract_audio else "video/mp4",
							}
							st.success("முடிந்தது. கீழே preview செய்து பதிவிறக்கலாம்.")
						except (ValueError, av.error.FFmpegError, OSError) as error:
							st.session_state["processed_result"] = None
							st.error(f"வீடியோவைச் செயலாக்க முடியவில்லை: {error}")

					result = st.session_state.get("processed_result")
					if result is not None:
						st.markdown("#### Result / வெளியீடு")
						if result["mime"] == "video/mp4":
							st.video(result["data"])
						st.download_button(
							"Download result / பதிவிறக்கவும்",
							data=result["data"],
							file_name=result["name"],
							mime=result["mime"],
							use_container_width=True,
						)

				with st.expander("AI editing / AI திருத்தம்"):
					st.write("AI editing is not enabled in this MVP. No AI service or API key is required; trimming, resizing, and audio export use video-processing tools only.")


