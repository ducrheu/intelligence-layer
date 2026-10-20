"""faster-whisper 本地转写（CPU、免 API key）。

用法：/home/huyi/hermes/venv/bin/python transcribe.py a.wav b.mp4 ...（Hermes 自己的 venv，已含 faster-whisper/numpy/Pillow/edge-tts，别再建第二个环境）
注意：首次加载 small/int8 约 136s（之后同进程内缓存），别在循环里反复新建进程。
"""
import sys
import time

from faster_whisper import WhisperModel

MODEL_DIR = "/home/huyi/hermes/models/whisper"   # 下载走 HF_ENDPOINT=https://hf-mirror.com
MODEL = "small"                                   # 要更准换 medium / large-v3


def main(paths: list[str]) -> int:
    t0 = time.time()
    model = WhisperModel(MODEL, device="cpu", compute_type="int8", download_root=MODEL_DIR)
    print(f"[模型加载] {time.time() - t0:.1f}s ({MODEL}/cpu/int8)")

    for path in paths:
        t1 = time.time()
        segments, info = model.transcribe(
            path, language="zh", vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
            # initial_prompt="用到的专有名词、术语",  # small 对同音词容易错，术语喂这里
        )
        segments = list(segments)
        print(f"\n=== {path} ===")
        print(f"语言={info.language} 置信={info.language_probability:.2f} "
              f"音频={info.duration:.1f}s 耗时={time.time() - t1:.1f}s")
        if not segments:
            print("  （无语音活动 → VAD 判定为纯音乐/噪声）")
        for s in segments:
            print(f"  [{s.start:6.2f}-{s.end:6.2f}] {s.text.strip()}")
        print("  全文:", "".join(s.text for s in segments).strip() or "(空)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1:]))
