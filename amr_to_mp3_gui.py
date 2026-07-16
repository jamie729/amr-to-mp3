"""
AMR / SILK v3 转 MP3 转换工具 — GUI 版本

依赖：
  - customtkinter（pip install customtkinter）
  - ffmpeg.exe（同目录或 PATH）
  - silk_decoder.exe（同目录，仅处理 QQ/SILK 格式时需要）
"""

import os
import subprocess
import sys
import json
import wave
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path
import shutil

# 打包后隐藏 cmd 窗口
_creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _subprocess_run(*args, **kwargs):
    kwargs.setdefault("creationflags", _creation_flags)
    return subprocess.run(*args, **kwargs)

def _app_dir() -> str:
    """打包后返回 exe 所在目录，开发时返回脚本目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

_CONFIG_PATH = os.path.join(_app_dir(), ".config.json")


def _load_theme():
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"theme_color": "green", "appearance": "light"}


def _save_theme(**kwargs):
    cfg = _load_theme()
    cfg.update(kwargs)
    try:
        with open(_CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
    except Exception:
        pass


_theme = _load_theme()
ctk.set_appearance_mode(_theme.get("appearance", "light"))
ctk.set_default_color_theme(_theme.get("theme_color", "green"))

DECODER = os.environ.get(
    "SILK_DECODER",
    os.path.join(_app_dir(), "silk_decoder.exe"),
)

SUPPORTED_INPUT_SUFFIXES = {".amr", ".silk"}


def _find_input_files(directory: Path) -> list[Path]:
    """Return supported audio files in a directory, case-insensitively."""
    return sorted(
        (path for path in directory.iterdir()
         if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES),
        key=lambda path: path.name.lower(),
    )


def _find_ffmpeg() -> str | None:
    local = os.path.join(_app_dir(), "ffmpeg.exe")
    if os.path.exists(local):
        return local
    p = os.environ.get("FFMPEG")
    if p and os.path.exists(p):
        return p
    try:
        r = _subprocess_run(
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
    return None


def _find_silk_offset(filepath: str) -> int:
    with open(filepath, "rb") as f:
        data = f.read(16)
    idx = data.find(b"#!SILK_V3")
    return idx if 0 <= idx <= 4 else -1


def _decode_silk(silk_input: str, pcm_output: str, decoder: str) -> bool:
    ret = _subprocess_run([decoder, silk_input, pcm_output], capture_output=True)
    return ret.returncode == 0 and os.path.exists(pcm_output)


def _pcm_to_wav(pcm_path: str, wav_path: str) -> None:
    with open(pcm_path, "rb") as f:
        data = f.read()
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(data)


def _ffmpeg_convert(ffmpeg_path: str, src_path: str, mp3_path: str) -> bool:
    ret = _subprocess_run(
        [ffmpeg_path, "-y", "-i", src_path,
         "-codec:a", "libmp3lame", "-b:a", "192k", mp3_path],
        capture_output=True,
    )
    return ret.returncode == 0


def convert_amr_to_mp3(amr_path: str, mp3_path: str,
                       ffmpeg_path: str, decoder: str) -> str | None:
    silk_offset = _find_silk_offset(amr_path)
    pcm_tmp = None
    wav_tmp = None
    try:
        if silk_offset == -1:
            if not _ffmpeg_convert(ffmpeg_path, amr_path, mp3_path):
                return "转换失败"
        else:
            if not os.path.exists(decoder):
                return "需要 silk_decoder.exe"
            pcm_tmp = amr_path + ".tmp.pcm"
            wav_tmp = amr_path + ".tmp.wav"
            if not _decode_silk(amr_path, pcm_tmp, decoder):
                return "silk 解码失败"
            _pcm_to_wav(pcm_tmp, wav_tmp)
            if not _ffmpeg_convert(ffmpeg_path, wav_tmp, mp3_path):
                return "ffmpeg 转换失败"

        shutil.copystat(amr_path, mp3_path)
        return None
    except Exception as e:
        return str(e)
    finally:
        for tmp in [pcm_tmp, wav_tmp]:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)


def _row(frame, label, entry_var, btn_text, btn_cmd, **kwargs):
    """Helper to build a row with label + entry + button."""
    ctk.CTkLabel(frame, text=label, font=("Microsoft YaHei", 13),
                 width=55).pack(side="left", padx=(16, 6), pady=10)
    entry = ctk.CTkEntry(frame, textvariable=entry_var, **kwargs)
    entry.pack(side="left", fill="x", expand=True, padx=6, pady=10)
    ctk.CTkButton(frame, text=btn_text, command=btn_cmd,
                  width=90, font=("Microsoft YaHei", 13)).pack(side="left", padx=(0, 16), pady=10)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AMR/SILK 转 MP3")
        self.geometry("680x520")
        self.resizable(True, True)
        self.minsize(560, 440)
        self.converting = False

        self.ffmpeg_var = ctk.StringVar(value=_find_ffmpeg() or "")
        self.input_var = ctk.StringVar()
        self.output_var = ctk.StringVar(value="-- 与输入同目录 --")
        self.mode_var = ctk.StringVar(value="single")

        self._build_ui()

        if not self.ffmpeg_var.get():
            self._pick_ffmpeg_dialog()

    def _build_ui(self):
        # —— 主题选择器 (固定，不重建) ——
        if not hasattr(self, "theme_frame"):
            self.theme_frame = ctk.CTkFrame(self)
            self.theme_frame.pack(anchor="ne", padx=16, pady=(8, 0))
            ctk.CTkLabel(self.theme_frame, text="主题:", font=("Microsoft YaHei", 12),
                         width=35).pack(side="left", padx=(8, 4), pady=4)
            self.appearance_var = ctk.StringVar(value=_theme.get("appearance", "dark"))
            ctk.CTkComboBox(self.theme_frame, variable=self.appearance_var,
                            values=["dark", "light"], width=70,
                            command=self._apply_appearance,
                            font=("Microsoft YaHei", 11)).pack(side="left", padx=2, pady=4)
            self.color_var = ctk.StringVar(value=_theme.get("theme_color", "blue"))
            ctk.CTkComboBox(self.theme_frame, variable=self.color_var,
                            values=["blue", "green"], width=80,
                            command=self._apply_color,
                            font=("Microsoft YaHei", 11)).pack(side="left", padx=2, pady=4)

        # —— 内容区 (可重建) ——
        # 销毁旧内容
        for child in self.winfo_children():
            if child is not self.theme_frame:
                child.destroy()

        # —— 标题 ——
        ctk.CTkLabel(self, text="AMR / SILK 转 MP3",
                     font=("Microsoft YaHei", 20, "bold")).pack(pady=(2, 2))

        # —— 模式选择 ——
        mode_frame = ctk.CTkFrame(self)
        mode_frame.pack(fill="x", padx=16, pady=(10, 8))
        ctk.CTkRadioButton(mode_frame, text="单文件", variable=self.mode_var,
                           value="single", command=self._toggle_mode,
                           font=("Microsoft YaHei", 13)).pack(side="left", padx=20, pady=10)
        ctk.CTkRadioButton(mode_frame, text="批量转换", variable=self.mode_var,
                           value="batch", command=self._toggle_mode,
                           font=("Microsoft YaHei", 13)).pack(side="left", padx=(0, 20), pady=10)

        # —— 输入 ——
        input_frame = ctk.CTkFrame(self)
        input_frame.pack(fill="x", padx=16, pady=(8, 8))
        self.input_frame_ref = input_frame
        _row(input_frame, "输入:", self.input_var,
             "选择文件", self._pick_input)
        self.input_btn = input_frame.winfo_children()[-1]
        self.input_entry = input_frame.winfo_children()[-2]

        # —— 输出 ——
        output_frame = ctk.CTkFrame(self)
        output_frame.pack(fill="x", padx=16, pady=(0, 8))
        self.output_frame_ref = output_frame
        _row(output_frame, "输出:", self.output_var,
             "选择", self._pick_output, placeholder_text="默认与输入同目录")

        # —— ffmpeg ——
        ffmpeg_frame = ctk.CTkFrame(self)
        ffmpeg_frame.pack(fill="x", padx=16, pady=(0, 8))
        _row(ffmpeg_frame, "ffmpeg:", self.ffmpeg_var,
             "选择", self._pick_ffmpeg_dialog,
             placeholder_text="ffmpeg.exe 路径")

        # —— 按钮 ——
        self.convert_btn = ctk.CTkButton(self, text="开始转换", command=self._start_convert,
                                         font=("Microsoft YaHei", 15, "bold"), height=42)
        self.convert_btn.pack(fill="x", padx=16, pady=(6, 6))

        # —— 进度条 ——
        self.progress = ctk.CTkProgressBar(self)
        self.progress.pack(fill="x", padx=16, pady=(0, 6))
        self.progress.set(0)

        # —— 日志 ——
        ctk.CTkLabel(self, text="日志", font=("Microsoft YaHei", 12, "bold")).pack(
            anchor="w", padx=16, pady=(2, 0))
        self.log_box = ctk.CTkTextbox(self, height=160, font=("Consolas", 11), wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(2, 10))

        self._toggle_mode()

    def _toggle_mode(self):
        mode = self.mode_var.get()
        if mode == "single":
            self.input_entry.configure(placeholder_text="选择要转换的文件...")
            self.input_btn.configure(text="选择文件")
        else:
            self.input_entry.configure(placeholder_text="选择包含 AMR / SILK 文件的文件夹...")
            self.input_btn.configure(text="选择文件夹")

    def _apply_appearance(self, _=None):
        mode = self.appearance_var.get()
        ctk.set_appearance_mode(mode)
        _save_theme(appearance=mode)

    def _apply_color(self, _=None):
        color = self.color_var.get()
        _save_theme(theme_color=color)
        ctk.set_default_color_theme(color)
        self._build_ui()

    def _pick_input(self):
        mode = self.mode_var.get()
        if mode == "single":
            f = filedialog.askopenfilename(
                title="选择 AMR / SILK 文件",
                filetypes=[
                    ("AMR / SILK 音频", "*.amr *.AMR *.silk *.SILK"),
                    ("所有文件", "*.*"),
                ],
            )
            if f:
                self.input_var.set(f)
        else:
            d = filedialog.askdirectory(title="选择包含 AMR / SILK 文件的目录")
            if d:
                self.input_var.set(d)

    def _pick_output(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.output_var.set(d)

    def _pick_ffmpeg_dialog(self):
        f = filedialog.askopenfilename(
            title="选择 ffmpeg.exe",
            defaultextension=".exe",
            filetypes=[("ffmpeg", "ffmpeg.exe"), ("所有文件", "*.*")],
        )
        if f:
            self.ffmpeg_var.set(f)

    def _start_convert(self):
        if self.converting:
            return
        ffmpeg_path = self.ffmpeg_var.get().strip()
        if not ffmpeg_path or not os.path.exists(ffmpeg_path):
            messagebox.showwarning("提示", "请指定有效的 ffmpeg.exe 路径")
            return
        input_path = self.input_var.get().strip()
        if not input_path:
            messagebox.showwarning("提示", "请选择输入")
            return
        if not os.path.exists(input_path):
            messagebox.showerror("错误", "输入路径不存在")
            return

        self.converting = True
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", "开始转换...\n\n")
        self.progress.set(0)
        threading.Thread(
            target=self._convert,
            args=(input_path, ffmpeg_path),
            daemon=True,
        ).start()

    def _convert(self, input_path, ffmpeg_path):
        decoder_path = DECODER

        if os.path.isfile(input_path):
            name = Path(input_path).stem
            out_val = self.output_var.get().strip()
            if out_val and out_val != "-- 与输入同目录 --":
                dst_dir = Path(out_val)
            else:
                dst_dir = Path(input_path).parent
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f"{name}.mp3"
            self._log(f"转换: {Path(input_path).name} -> {dst.name}")
            exp = os.path.expandvars(os.path.expanduser(decoder_path))
            err = convert_amr_to_mp3(input_path, str(dst), ffmpeg_path, exp)
            if err is None:
                self._log("  成功 ✓")
            else:
                self._log(f"  失败 ✗: {err}")
            self._log("\n完成!")
        else:
            src = Path(input_path)
            out_val = self.output_var.get().strip()
            dst = Path(out_val) if out_val and out_val != "-- 与输入同目录 --" else src
            dst.mkdir(parents=True, exist_ok=True)

            input_files = _find_input_files(src)
            if not input_files:
                self._log("未找到 AMR / SILK 文件")
                self._on_done()
                return

            self._log(f"找到 {len(input_files)} 个 AMR / SILK 文件\n")
            exp = os.path.expandvars(os.path.expanduser(decoder_path))
            success = fail = 0

            for i, input_file in enumerate(input_files, 1):
                mp3_file = dst / f"{input_file.stem}.mp3"
                self._log(f"[{i}/{len(input_files)}] {input_file.name} -> {mp3_file.name}")
                err = convert_amr_to_mp3(str(input_file), str(mp3_file), ffmpeg_path, exp)
                if err is None:
                    success += 1
                    self._log("  成功 ✓")
                else:
                    fail += 1
                    self._log(f"  失败 ✗: {err}")
                self.after(0, lambda p=i / len(input_files): self.progress.set(p))

            self._log(f"\n完成! 成功 {success}, 失败 {fail}")

        self._on_done()

    def _on_done(self):
        self.progress.set(1)
        self.converting = False

    def _log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")


if __name__ == "__main__":
    app = App()
    app.mainloop()
