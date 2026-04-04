"""
AMR / SILK v3 转 MP3 批量转换工具

依赖：
  - ffmpeg.exe（同目录或 PATH）
  - silk_decoder.exe（同目录，仅处理 QQ/SILK 格式时需要）
"""

import os
import sys
import shutil
import subprocess
import wave
import argparse
from pathlib import Path


def _app_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _find_ffmpeg() -> str:
    local = os.path.join(_app_dir(), "ffmpeg.exe")
    if os.path.exists(local):
        return local
    p = os.environ.get("FFMPEG")
    if p and os.path.exists(p):
        return p
    try:
        r = subprocess.run(
            [r"C:\Windows\System32\where.exe", "ffmpeg"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    import shutil as _shutil
    found = _shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError("ffmpeg not found. 请将 ffmpeg.exe 放在同目录或设置环境变量 FFMPEG")


FFMPEG = _find_ffmpeg()

DECODER = os.environ.get(
    "SILK_DECODER",
    os.path.join(_app_dir(), "silk_decoder.exe"),
)


def _find_silk_offset(filepath: str) -> int:
    with open(filepath, "rb") as f:
        data = f.read(16)
    idx = data.find(b"#!SILK_V3")
    return idx if 0 <= idx <= 4 else -1


def _decode_silk(silk_input: str, pcm_output: str) -> bool:
    ret = subprocess.run([DECODER, silk_input, pcm_output], capture_output=True)
    return ret.returncode == 0 and os.path.exists(pcm_output)


def _pcm_to_wav(pcm_path: str, wav_path: str) -> None:
    with open(pcm_path, "rb") as f:
        data = f.read()
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(data)


def _ffmpeg_convert(src_path: str, mp3_path: str) -> bool:
    ret = subprocess.run(
        [FFMPEG, "-y", "-i", src_path, "-codec:a", "libmp3lame", "-b:a", "192k", mp3_path],
        capture_output=True,
    )
    return ret.returncode == 0


def convert_amr_to_mp3(amr_path: str, mp3_path: str) -> bool:
    silk_offset = _find_silk_offset(amr_path)
    pcm_tmp = None
    wav_tmp = None

    try:
        if silk_offset == -1:
            if not _ffmpeg_convert(amr_path, mp3_path):
                print(f"  转换失败: {amr_path}")
                return False
        else:
            if not os.path.exists(DECODER):
                print(f"  跳过 (需要 silk_decoder.exe): {amr_path}")
                return False
            pcm_tmp = amr_path + ".tmp.pcm"
            wav_tmp = amr_path + ".tmp.wav"
            if not _decode_silk(amr_path, pcm_tmp):
                print(f"  silk 解码失败: {amr_path}")
                return False
            _pcm_to_wav(pcm_tmp, wav_tmp)
            if not _ffmpeg_convert(wav_tmp, mp3_path):
                return False

        shutil.copystat(amr_path, mp3_path)
        return True
    except Exception as e:
        print(f"  转换失败: {e}")
        return False
    finally:
        for tmp in [pcm_tmp, wav_tmp]:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)


def batch_convert(input_dir: str, output_dir: str | None = None) -> None:
    src = Path(input_dir)
    dst = Path(output_dir) if output_dir else src

    if not src.is_dir():
        print(f"Error: {src} 不是有效目录")
        return

    dst.mkdir(parents=True, exist_ok=True)

    amr_files = list(set(src.glob("*.amr")) | set(src.glob("*.AMR")))
    if not amr_files:
        print(f"{src} 下没有找到 AMR 文件")
        return

    print(f"找到 {len(amr_files)} 个 AMR 文件\n")
    success = fail = 0

    for amr_file in amr_files:
        mp3_file = dst / f"{amr_file.stem}.mp3"
        print(f"转换: {amr_file.name} -> {mp3_file.name}")
        if convert_amr_to_mp3(str(amr_file), str(mp3_file)):
            success += 1
        else:
            fail += 1

    print(f"\n完成! 成功 {success}, 失败 {fail}")


def convert_single(input_path: str, output_path: str | None = None) -> None:
    src = Path(input_path)
    if not src.is_file():
        print(f"Error: {src} 不是有效文件")
        return

    dst = Path(output_path) if output_path else src.with_suffix(".mp3")
    print(f"转换: {src.name} -> {dst.name}")
    if convert_amr_to_mp3(str(src), str(dst)):
        print(f"成功: {dst}")
    else:
        print("转换失败")


def main():
    parser = argparse.ArgumentParser(description="AMR/SILK v3 转 MP3")
    parser.add_argument("-i", "--input", required=True, help="输入的 AMR 文件或目录")
    parser.add_argument("-o", "--output", default=None, help="输出的文件或目录（默认同位置）")
    args = parser.parse_args()

    if Path(args.input).is_dir():
        batch_convert(args.input, args.output)
    else:
        convert_single(args.input, args.output)


if __name__ == "__main__":
    main()
