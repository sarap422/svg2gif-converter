#!/usr/bin/env python3
"""
SVG to GIF Converter ver.0.1.0
- fpsのみでフレーム品質を制御（フレーム数は自動計算）
- 総再生時間と総フレーム数を自動表示
- 順番アニメーションを維持
- 文字化けを除去
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from dataclasses import dataclass
from typing import List, Optional
import time
import threading
import re
from abc import ABC, abstractmethod
from pathlib import Path

# Model: データとビジネスロジックを管理
@dataclass
class ConversionSettings:
    svg_file: str
    output_dir: str
    gif_output: str
    fps: int
    animation_duration: float  # 元アニメーションの総時間
    
    @property
    def frame_count(self) -> int:
        """fpsと総時間から自動計算されるフレーム数"""
        return max(10, int(self.animation_duration * self.fps))
    
    @property 
    def frame_duration_ms(self) -> int:
        """フレーム間隔（ミリ秒）"""
        return int(1000 / self.fps)

class ConversionModel:
    def __init__(self):
        self.settings: Optional[ConversionSettings] = None
        self._observers: List[IConversionObserver] = []
        self.is_converting = False
    
    def add_observer(self, observer: 'IConversionObserver'):
        self._observers.append(observer)
    
    def notify_progress(self, progress: int, message: str):
        for observer in self._observers:
            observer.on_progress_update(progress, message)
    
    def detect_animation_info(self, svg_content: str) -> tuple:
        """SVGファイルからアニメーション情報を詳細に検出"""
        base_duration = 1.0  # デフォルト値
        max_delay = 0
        has_delays = False
        
        # CSSアニメーションのdurationを検出
        css_pattern = r'animation:[^;]*?(\d+(?:\.\d+)?)(s|ms)'
        matches = re.findall(css_pattern, svg_content)
        if matches:
            for match in matches:
                value = float(match[0])
                if match[1] == 'ms':
                    value = value / 1000
                base_duration = max(base_duration, value)
        
        # animation-delayの最大値を検出
        delay_patterns = [
            r'animation-delay:\s*(\d+(?:\.\d+)?)(s|ms)',
            r'animation-delay:\s*\.(\d+)(s)?'  # .45s のような形式にも対応
        ]
        
        for pattern in delay_patterns:
            delay_matches = re.findall(pattern, svg_content)
            for match in delay_matches:
                if len(match) >= 1:
                    # .45s のような形式の場合
                    if pattern == r'animation-delay:\s*\.(\d+)(s)?':
                        value = float('0.' + match[0])
                    else:
                        value = float(match[0])
                        if len(match) > 1 and match[1] == 'ms':
                            value = value / 1000
                    max_delay = max(max_delay, value)
                    has_delays = True
        
        # トータルアニメーション時間 = base_duration + max_delay
        total_duration = base_duration + max_delay
        
        # SMILアニメーションのdurを検出
        smil_pattern = r'dur="(\d+(?:\.\d+)?)(s|ms)?"'
        matches = re.findall(smil_pattern, svg_content)
        if matches:
            for match in matches:
                value = float(match[0])
                if match[1] == 'ms':
                    value = value / 1000
                total_duration = max(total_duration, value)
        
        return total_duration, has_delays
    
    def calculate_optimal_settings(self, svg_file: str) -> tuple:
        """SVGファイルから最適な設定を計算"""
        try:
            with open(svg_file, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # アニメーション時間とdelay情報を検出
            animation_duration, has_delays = self.detect_animation_info(svg_content)
            
            # blocks-scaleの場合は固定値を使用
            if 'spinner_' in svg_content and has_delays:
                return 1.65, 20  # blocks-scale用の最適値（1.65秒、20fps）
            
            # その他のSVGの場合
            optimal_fps = 20  # デフォルト20fps
            
            return animation_duration, optimal_fps
        except:
            return 1.65, 20  # デフォルト値
    
    def convert_svg_to_gif(self, settings: ConversionSettings):
        self.settings = settings
        self.is_converting = True
        
        try:
            # 出力ディレクトリの作成
            output_dir = Path(settings.output_dir)
            if not output_dir.exists():
                output_dir.mkdir(parents=True, exist_ok=True)
            
            # GIFファイルのフルパスを生成
            gif_filename = settings.gif_output
            if not gif_filename.endswith('.gif'):
                gif_filename = f"{gif_filename}.gif"
            gif_path = output_dir / gif_filename
            
            # 一時フレーム用ディレクトリ
            temp_frames_dir = output_dir / "temp_frames"
            if not temp_frames_dir.exists():
                temp_frames_dir.mkdir(parents=True, exist_ok=True)

            # ブラウザセットアップ
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=800x800")
            options.add_argument("--force-device-scale-factor=2")
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)

            # SVGファイルの内容を読み込み
            with open(settings.svg_file, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # HTMLページを作成（アニメーションを正確に制御）
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{
                        margin: 0;
                        padding: 0;
                        background: white;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                    }}
                    #svg-container {{
                        display: flex;
                        justify-content: center;
                        align-items: center;
                    }}
                </style>
            </head>
            <body>
                <div id="svg-container">
                    {svg_content}
                </div>
                <script>
                    // 全アニメーションを初期化
                    document.querySelectorAll('*').forEach(el => {{
                        if (el.style.animation) {{
                            el.style.animationPlayState = 'paused';
                        }}
                    }});
                    
                    function setAnimationProgress(progress) {{
                        // progress: 0.0 から 1.0
                        const totalDuration = {settings.animation_duration};
                        const currentTime = progress * totalDuration;
                        
                        // 各要素のアニメーションを個別に制御
                        document.querySelectorAll('[class*="spinner_"]').forEach(el => {{
                            const className = el.className.baseVal || el.className;
                            let delay = 0;
                            
                            // クラス名からdelayを判定（順番アニメーション）
                            if (className.includes('spinner_LWk7')) {{
                                delay = 0;  // 左上（最初）
                            }} else if (className.includes('spinner_yOMU')) {{
                                delay = 0.15;  // 右上（2番目）
                            }} else if (className.includes('spinner_KS4S')) {{
                                delay = 0.3;  // 右下（3番目）
                            }} else if (className.includes('spinner_zVee')) {{
                                delay = 0.45;  // 左下（4番目）
                            }}
                            
                            // アニメーションの進行を計算
                            const animDuration = 1.2; // 各アニメーションの時間
                            const effectiveTime = currentTime - delay;
                            
                            if (effectiveTime < 0) {{
                                // まだ開始していない
                                el.style.animationDelay = '999s';
                                el.style.animationPlayState = 'paused';
                            }} else {{
                                // アニメーション中
                                const animProgress = (effectiveTime % animDuration);
                                el.style.animationDelay = `-${{animProgress}}s`;
                                el.style.animationPlayState = 'paused';
                            }}
                        }});
                        
                        // SMILアニメーションも制御
                        document.querySelectorAll('animate, animateTransform').forEach(el => {{
                            el.setAttribute('begin', `-${{currentTime}}s`);
                        }});
                    }}
                </script>
            </body>
            </html>
            """
            
            # 一時HTMLファイルを作成
            temp_html = temp_frames_dir / 'temp.html'
            with open(temp_html, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # HTMLを表示
            driver.get(f"file://{temp_html.absolute()}")
            time.sleep(1.5)

            frames = []
            frame_count = settings.frame_count
            
            # フレームキャプチャ
            for i in range(frame_count):
                frame_file = temp_frames_dir / f"frame_{i:04d}.png"
                
                # アニメーションの進行状態を時間ベースで計算（0.0 から 1.0）
                time_per_frame = settings.animation_duration / frame_count
                current_time = i * time_per_frame
                progress = current_time / settings.animation_duration if settings.animation_duration > 0 else 0
                # 最後のフレームは確実に1.0にする
                if i == frame_count - 1:
                    progress = 1.0
                
                # JavaScriptでアニメーションの進行状態を設定
                driver.execute_script(f"setAnimationProgress({progress});")
                
                # レンダリング待機
                time.sleep(0.15)
                
                # スクリーンショット保存
                driver.save_screenshot(str(frame_file))
                frames.append(str(frame_file))
                
                progress_percent = int((i + 1) / frame_count * 50)
                self.notify_progress(progress_percent, f"フレーム {i+1}/{frame_count} を生成中...")

            driver.quit()

            # GIFに結合
            self.notify_progress(75, f"フレームをGIFに結合中... (生成フレーム数: {len(frames)})")
            
            # 各フレームを読み込んで処理
            images = []
            duration_ms = settings.frame_duration_ms
            
            for i, frame_file in enumerate(frames):
                img = Image.open(frame_file)
                # 白い余白を削除
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                # RGBAをRGBに変換（GIFはRGBが推奨）
                if img.mode == 'RGBA':
                    # 白背景と合成
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3] if len(img.split()) > 3 else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # フレーム重複防止（右下の1ピクセルを微調整）
                pixels = img.load()
                width, height = img.size
                if width > 1 and height > 1:
                    # 各フレームを微妙に異なるものにする
                    r, g, b = pixels[width-1, height-1]
                    pixels[width-1, height-1] = (r, g, (b + i) % 256)
                
                images.append(img)
            
            # 実際のフレーム数を確認
            actual_frame_count = len(images)
            print(f"デバッグ: 指定フレーム数={frame_count}, 実際の画像数={actual_frame_count}")
            print(f"デバッグ: 設定fps={settings.fps}, フレーム間隔={duration_ms}ms")
            print(f"デバッグ: アニメーション時間={settings.animation_duration}秒")
            print(f"デバッグ: 1フレーム当たりの時間={settings.animation_duration/frame_count:.4f}秒")
            print(f"デバッグ: 期待される総再生時間={frame_count * duration_ms / 1000:.4f}秒")
            
            # 各フレームの表示時間リストを作成（すべて同じ値）
            durations = [duration_ms] * actual_frame_count
            
            # GIFとして保存（最適化とdisposal設定を変更）
            images[0].save(
                str(gif_path),
                save_all=True,
                append_images=images[1:],
                duration=durations,
                loop=0,
                optimize=False,  # 最適化を無効（フレーム数を保持）
                disposal=2  # 各フレームを完全に置き換える
            )
            
            # 保存後のGIFファイルのフレーム数を確認
            try:
                with Image.open(gif_path) as check_img:
                    saved_frame_count = 0
                    try:
                        while True:
                            saved_frame_count += 1
                            check_img.seek(check_img.tell() + 1)
                    except EOFError:
                        pass
                print(f"デバッグ: 保存されたGIFのフレーム数={saved_frame_count}")
            except Exception as e:
                print(f"GIFフレーム数確認エラー: {e}")
            
            self.notify_progress(85, f"GIF保存完了 (フレーム数: {actual_frame_count}, fps: {settings.fps})")

            self.notify_progress(90, "一時ファイルを削除中...")
            
            # 一時ファイルを削除
            for frame_file in frames:
                try:
                    os.remove(frame_file)
                except:
                    pass
            
            # 一時ディレクトリとHTMLファイルを削除
            try:
                if temp_html.exists():
                    temp_html.unlink()
                if temp_frames_dir.exists():
                    temp_frames_dir.rmdir()
            except:
                pass

            self.notify_progress(100, f"変換完了! 保存先: {gif_path}")
                    
        except Exception as e:
            self.notify_progress(-1, f"エラーが発生しました: {str(e)}")
        finally:
            self.is_converting = False

# Observer Interface
class IConversionObserver(ABC):
    @abstractmethod
    def on_progress_update(self, progress: int, message: str):
        pass

# Controller
class ConversionController:
    def __init__(self, model: ConversionModel, view: 'ConversionView'):
        self.model = model
        self.view = view
        
    def start_conversion(self, settings: ConversionSettings):
        if self.model.is_converting:
            messagebox.showwarning("警告", "変換処理が既に実行中です")
            return
            
        thread = threading.Thread(
            target=self.model.convert_svg_to_gif,
            args=(settings,)
        )
        thread.daemon = True
        thread.start()
    
    def analyze_svg(self, svg_file: str):
        """SVGファイルを解析して最適な設定を提案"""
        return self.model.calculate_optimal_settings(svg_file)

# View
class ConversionView(tk.Tk, IConversionObserver):
    def __init__(self):
        super().__init__()

        self.title("SVG to GIF Converter ver.0.1.0")
        self.geometry("700x500")
        self.model = ConversionModel()
        self.controller = ConversionController(self.model, self)
        self.model.add_observer(self)
        
        # デフォルトのダウンロードフォルダを設定
        self.default_output_path = str(Path.home() / "Downloads")
        
        # アニメーション時間（検出された値）
        self.animation_duration = 1.65  # デフォルト値
        
        self._create_widgets()
        self._setup_layout()
        
    def _create_widgets(self):
        # 入力ファイル選択
        self.file_frame = ttk.LabelFrame(self, text="入力/出力設定", padding=10)
        self.svg_path = tk.StringVar()
        self.output_path = tk.StringVar(value=self.default_output_path)
        self.gif_path = tk.StringVar(value="animation.gif")
        
        # SVGファイル入力
        ttk.Label(self.file_frame, text="SVGファイル:").grid(row=0, column=0, sticky="w")
        self.svg_entry = ttk.Entry(self.file_frame, textvariable=self.svg_path, width=50)
        self.svg_entry.grid(row=0, column=1, padx=5)
        ttk.Button(self.file_frame, text="参照", command=self._browse_svg).grid(row=0, column=2)
        
        # 出力フォルダ
        ttk.Label(self.file_frame, text="出力フォルダ:").grid(row=1, column=0, sticky="w")
        self.output_entry = ttk.Entry(self.file_frame, textvariable=self.output_path, width=50)
        self.output_entry.grid(row=1, column=1, padx=5, pady=(10, 0))
        ttk.Button(self.file_frame, text="選択", command=self._browse_output_dir).grid(row=1, column=2, pady=(10, 0))
        
        # GIFファイル名
        ttk.Label(self.file_frame, text="GIFファイル名:").grid(row=2, column=0, sticky="w")
        self.gif_entry = ttk.Entry(self.file_frame, textvariable=self.gif_path, width=50)
        self.gif_entry.grid(row=2, column=1, padx=5, pady=(10, 0))
        
        # アニメーション情報表示
        self.info_frame = ttk.LabelFrame(self, text="アニメーション情報", padding=10)
        self.animation_info = tk.StringVar(value="SVGファイルを選択してください")
        ttk.Label(self.info_frame, textvariable=self.animation_info, foreground="blue").pack()
        
        # パラメータ設定
        self.param_frame = ttk.LabelFrame(self, text="変換設定", padding=10)
        self.fps = tk.IntVar(value=20)  # デフォルト20fps
        
        # fps設定の行
        ttk.Label(self.param_frame, text="フレームレート(fps):").grid(row=0, column=0, sticky="w")
        self.fps_scale = ttk.Scale(self.param_frame, from_=5, to=30, variable=self.fps, 
                                  orient="horizontal", command=lambda x: self._on_fps_changed())
        self.fps_scale.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        
        # fpsの数値入力フィールド
        self.fps_entry = ttk.Entry(self.param_frame, textvariable=self.fps, width=8)
        self.fps_entry.grid(row=0, column=2, padx=(0, 5))
        self.fps_entry.bind('<Return>', lambda e: self._on_fps_changed())
        self.fps_entry.bind('<FocusOut>', lambda e: self._on_fps_changed())
        
        # 計算結果表示
        self.calc_info = tk.StringVar(value="総再生時間: -- 秒  |  総フレーム数: --")
        ttk.Label(self.param_frame, textvariable=self.calc_info, foreground="green").grid(row=1, column=0, columnspan=3, pady=(10, 0))
        
        # 自動設定ボタン
        ttk.Button(self.param_frame, text="最適値を自動設定", command=self._auto_configure).grid(row=2, column=1, pady=10)
        
        # 変換ボタンとプログレスバー
        self.control_frame = ttk.Frame(self, padding=10)
        self.convert_btn = ttk.Button(self.control_frame, text="変換開始", command=self._start_conversion)
        self.progress = ttk.Progressbar(self.control_frame, length=400, mode='determinate')
        self.status_label = ttk.Label(self.control_frame, text="準備完了")
        
    def _setup_layout(self):
        self.file_frame.pack(fill="x", padx=10, pady=5)
        self.info_frame.pack(fill="x", padx=10, pady=5)
        self.param_frame.pack(fill="x", padx=10, pady=5)
        self.control_frame.pack(fill="x", padx=10, pady=5)
        
        self.convert_btn.pack(pady=5)
        self.progress.pack(pady=5)
        self.status_label.pack(pady=5)
        
        # グリッドの列幅を調整
        self.param_frame.columnconfigure(1, weight=1)
    
    def _on_fps_changed(self):
        """fps変更時に計算結果を更新"""
        try:
            fps = int(self.fps.get())
            if fps < 5:
                fps = 5
                self.fps.set(fps)
            elif fps > 30:
                fps = 30
                self.fps.set(fps)
            
            # 総フレーム数を計算
            total_frames = max(10, int(self.animation_duration * fps))
            actual_duration = total_frames / fps
            
            # 表示を更新
            self.calc_info.set(f"総再生時間: {actual_duration:.2f}秒  |  総フレーム数: {total_frames}")
            
        except:
            self.fps.set(20)
            self._on_fps_changed()
    
    def _browse_svg(self):
        filename = filedialog.askopenfilename(
            initialdir=self.default_output_path,
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")]
        )
        if filename:
            self.svg_path.set(filename)
            self._on_svg_selected()
    
    def _browse_output_dir(self):
        """出力フォルダを選択"""
        dirname = filedialog.askdirectory(
            initialdir=self.output_path.get() or self.default_output_path,
            title="出力フォルダを選択"
        )
        if dirname:
            self.output_path.set(dirname)
    
    def _on_svg_selected(self):
        """SVGファイルが選択されたときの処理"""
        svg_path = self.svg_path.get()
        if svg_path and os.path.exists(svg_path):
            # ファイル名からGIFファイル名を生成
            svg_filename = Path(svg_path).stem
            gif_name = f"{svg_filename}.gif" if not svg_filename.endswith('.gif') else svg_filename
            self.gif_path.set(gif_name)
            
            # 自動設定を実行
            self._auto_configure()
            
    def _auto_configure(self):
        """SVGファイルを解析して最適な設定を自動適用"""
        if not self.svg_path.get() or not os.path.exists(self.svg_path.get()):
            return
        
        animation_duration, fps = self.controller.analyze_svg(self.svg_path.get())
        
        # 検出された値を保存
        self.animation_duration = animation_duration
        self.fps.set(int(fps))
        
        # 表示を更新
        info_text = f"検出されたアニメーション時間: {animation_duration:.2f}秒\n"
        info_text += f"推奨設定: {fps}fps"
        self.animation_info.set(info_text)
        
        # 計算結果を更新
        self._on_fps_changed()
            
    def _start_conversion(self):
        if not self.svg_path.get() or not os.path.exists(self.svg_path.get()):
            messagebox.showerror("エラー", "SVGファイルが見つかりません")
            return
        
        # 出力パスの検証
        output_dir = self.output_path.get()
        if not output_dir:
            output_dir = self.default_output_path
            self.output_path.set(output_dir)
        
        # 出力ディレクトリが存在しない場合は作成を試みる
        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("エラー", f"出力フォルダを作成できません: {str(e)}")
            return
            
        settings = ConversionSettings(
            svg_file=self.svg_path.get(),
            output_dir=output_dir,
            gif_output=self.gif_path.get(),
            fps=int(self.fps.get()),
            animation_duration=self.animation_duration
        )
        
        self.controller.start_conversion(settings)
        
    def on_progress_update(self, progress: int, message: str):
        if progress >= 0:
            self.progress['value'] = progress
        self.status_label['text'] = message
        
        if progress == 100:
            messagebox.showinfo("完了", message)
        elif progress == -1:
            messagebox.showerror("エラー", message)

def main():
    app = ConversionView()
    app.mainloop()

if __name__ == "__main__":
    main()
