#!/usr/bin/env python3
"""
SVG to GIF Converter ver.1.1.2
- 各要素の元のanimation-delayを保持した正確な制御
- 個別要素のタイミングを独立して管理
- ループ回数設定を削除（総再生時間内で自然にループ）
- デバッグモードの改善
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
import json

# Model: データとビジネスロジックを管理
@dataclass
class ConversionSettings:
    svg_file: str
    output_dir: str
    gif_output: str
    fps: int
    animation_duration: float  # 元アニメーションの総時間
    fade_in_duration: float = 0.0  # フェードイン時間（秒）
    fade_out_duration: float = 0.0  # フェードアウト時間（秒）
    start_delay: float = 0.0  # 開始前の透明時間（秒）
    end_delay: float = 0.0  # 終了後の透明時間（秒）
    debug_mode: bool = False  # デバッグモード
    
    @property
    def frame_count(self) -> int:
        """fpsと総時間から自動計算されるフレーム数"""
        total_time = self.animation_duration + self.start_delay + self.end_delay
        return max(10, int(total_time * self.fps))
    
    @property 
    def frame_duration_ms(self) -> int:
        """フレーム間隔（ミリ秒）- 実際の総再生時間を考慮"""
        total_time = self.animation_duration + self.start_delay + self.end_delay
        frame_count = self.frame_count
        # 総再生時間をフレーム数で割って、各フレームの表示時間を計算
        duration = int((total_time * 1000) / frame_count)
        # GIFの互換性のため、最小50ms（20fps相当）を保証
        return max(50, duration)

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
    
    def detect_animation_info(self, svg_content: str, debug: bool = False) -> tuple:
        """SVGファイルからアニメーション情報を詳細に検出"""
        base_duration = 0.0
        max_delay = 0
        has_delays = False
        
        if debug:
            print(f"=== アニメーション検出開始 ===")
        
        # CSSアニメーションのdurationを検出
        css_patterns = [
            r'animation:[^;]*?(\d*\.?\d+)(s|ms)',
            r'animation-duration:\s*(\d*\.?\d+)(s|ms)',
        ]
        
        for i, pattern in enumerate(css_patterns):
            matches = re.findall(pattern, svg_content)
            if debug:
                print(f"パターン{i+1}: {pattern}")
                print(f"検出された値: {matches}")
            if matches:
                for match in matches:
                    value_str = match[0]
                    if value_str:
                        value = float(value_str)
                        if match[1] == 'ms':
                            value = value / 1000
                        if debug:
                            print(f"  変換後の値: {value}秒")
                        base_duration = max(base_duration, value)
        
        if debug:
            print(f"検出されたbase_duration: {base_duration}秒")
        
        # animation-delayの最大値を検出
        delay_patterns = [
            r'animation-delay:\s*(\d*\.?\d+)(s|ms)',
            r'animation-delay:\s*\.(\d+)(s)?'
        ]
        
        for i, pattern in enumerate(delay_patterns):
            delay_matches = re.findall(pattern, svg_content)
            if debug:
                print(f"Delayパターン{i+1}: {pattern}")
                print(f"検出されたdelay: {delay_matches}")
            for match in delay_matches:
                if len(match) >= 1:
                    if pattern == r'animation-delay:\s*\.(\d+)(s)?':
                        value = float('0.' + match[0])
                    else:
                        value = float(match[0])
                        if len(match) > 1 and match[1] == 'ms':
                            value = value / 1000
                    if debug:
                        print(f"  変換後のdelay: {value}秒")
                    max_delay = max(max_delay, value)
                    has_delays = True
        
        if debug:
            print(f"検出されたmax_delay: {max_delay}秒")
        
        # トータルアニメーション時間 = base_duration + max_delay
        total_duration = base_duration + max_delay
        if debug:
            print(f"計算されたtotal_duration: {total_duration}秒")
        
        # SMILアニメーションのdurを検出
        smil_pattern = r'dur="(\d+(?:\.\d+)?)(s|ms)?"'
        matches = re.findall(smil_pattern, svg_content)
        if matches:
            if debug:
                print(f"SMILアニメーション検出: {matches}")
            for match in matches:
                value = float(match[0])
                if len(match) > 1 and match[1] == 'ms':
                    value = value / 1000
                total_duration = max(total_duration, value)
        
        # 何も検出されなかった場合のフォールバック
        if total_duration == 0:
            total_duration = 1.0
            if debug:
                print("何も検出されず、デフォルト値1.0秒を使用")
        
        if debug:
            print(f"最終的なtotal_duration: {total_duration}秒, has_delays: {has_delays}")
            print(f"=== アニメーション検出終了 ===")
        
        return total_duration, has_delays
    
    def get_gif_info(self, filepath: str) -> tuple:
        """GIFファイルの情報を取得（総再生時間、フレーム数、fps）"""
        try:
            with Image.open(filepath) as im:
                total_duration = 0
                frame_count = 0
                try:
                    while True:
                        duration = im.info.get('duration', 0)
                        total_duration += duration
                        frame_count += 1
                        im.seek(im.tell() + 1)
                except EOFError:
                    pass
                
                duration_seconds = total_duration / 1000
                fps = frame_count / duration_seconds if duration_seconds > 0 else 0
                return duration_seconds, frame_count, fps
        except Exception as e:
            print(f"GIF解析エラー: {e}")
            return 0, 0, 0
    
    def calculate_optimal_settings(self, file_path: str) -> tuple:
        """ファイルを解析して最適な設定を計算（SVGまたはGIF）"""
        try:
            file_extension = Path(file_path).suffix.lower()
            
            if file_extension == '.gif':
                duration, frame_count, fps = self.get_gif_info(file_path)
                return duration, int(fps) if fps > 0 else 20
            
            elif file_extension == '.svg':
                with open(file_path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()
                
                animation_duration, has_delays = self.detect_animation_info(svg_content)
                optimal_fps = 20  # デフォルト20fps
                return animation_duration, optimal_fps
            
            else:
                return 1.65, 20
                
        except:
            return 1.65, 20
    
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
            
            # HTMLページを作成（改善されたアニメーション制御）
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
                    // 元のアニメーション情報を保存
                    const animationInfo = new Map();
                    
                    // 初期化時に各要素の元の設定を保存
                    document.querySelectorAll('[class]').forEach(el => {{
                        const className = el.className.baseVal || el.className || '';
                        if (className) {{
                            const computed = window.getComputedStyle(el);
                            const animName = computed.animationName;
                            const animDuration = computed.animationDuration;
                            const animDelay = computed.animationDelay;
                            
                            if (animName && animName !== 'none') {{
                                animationInfo.set(el, {{
                                    className: className,
                                    animationName: animName,
                                    duration: parseFloat(animDuration) || 0,
                                    delay: parseFloat(animDelay) || 0,
                                    originalDuration: animDuration,
                                    originalDelay: animDelay
                                }});
                                
                                // 初期状態で一時停止
                                el.style.animationPlayState = 'paused';
                            }}
                        }}
                    }});
                    
                    // SMILアニメーションも初期化
                    document.querySelectorAll('animate, animateTransform').forEach(el => {{
                        el.setAttribute('begin', 'indefinite');
                    }});
                    
                    function setAnimationProgress(progress, frameNumber) {{
                        // progress: 0.0 から 1.0
                        const totalDuration = {settings.animation_duration};
                        const currentTime = progress * totalDuration;
                        
                        const frameLog = {{
                            frame: frameNumber,
                            progress: progress,
                            currentTime: currentTime,
                            totalDuration: totalDuration,
                            elements: []
                        }};
                        
                        // 各要素のアニメーションを個別に制御
                        animationInfo.forEach((info, el) => {{
                            const elementStartTime = info.delay;
                            const elementDuration = info.duration;
                            
                            // この要素のアニメーションが開始しているかチェック
                            if (currentTime >= elementStartTime) {{
                                // この要素における経過時間
                                const elementTime = currentTime - elementStartTime;
                                
                                // アニメーションの進行状態を設定
                                // 負の値のdelayを使用してアニメーションを特定の位置に設定
                                el.style.animationDelay = `-${{elementTime}}s`;
                                el.style.animationPlayState = 'paused';
                                
                                // デバッグ情報
                                if (elementDuration > 0) {{
                                    const loops = Math.floor(elementTime / elementDuration);
                                    const timeInCurrentLoop = elementTime % elementDuration;
                                    const progressInLoop = timeInCurrentLoop / elementDuration;
                                    
                                    frameLog.elements.push({{
                                        class: info.className,
                                        animationName: info.animationName,
                                        duration: info.duration,
                                        originalDelay: info.delay,
                                        appliedDelay: -elementTime,
                                        elementTime: elementTime,
                                        loops: loops,
                                        timeInCurrentLoop: timeInCurrentLoop,
                                        progressInLoop: progressInLoop
                                    }});
                                }}
                            }} else {{
                                // まだ開始していない要素は初期状態を保持
                                el.style.animationDelay = `${{info.delay}}s`;
                                el.style.animationPlayState = 'paused';
                                
                                frameLog.elements.push({{
                                    class: info.className,
                                    animationName: info.animationName,
                                    duration: info.duration,
                                    originalDelay: info.delay,
                                    appliedDelay: info.delay,
                                    elementTime: 0,
                                    status: 'not_started'
                                }});
                            }}
                        }});
                        
                        // SMILアニメーションの制御
                        document.querySelectorAll('animate, animateTransform').forEach(el => {{
                            el.setAttribute('begin', `-${{currentTime}}s`);
                        }});
                        
                        return frameLog;
                    }}
                    
                    // アニメーション情報を取得
                    function getAnimationSummary() {{
                        const summary = [];
                        animationInfo.forEach((info, el) => {{
                            summary.push({{
                                class: info.className,
                                animationName: info.animationName,
                                duration: info.duration,
                                delay: info.delay
                            }});
                        }});
                        return summary;
                    }}
                    
                    // グローバルに公開
                    window.animationInfo = animationInfo;
                    window.setAnimationProgress = setAnimationProgress;
                    window.getAnimationSummary = getAnimationSummary;
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
            
            # アニメーション情報を取得してデバッグ出力
            if settings.debug_mode:
                animation_summary = driver.execute_script("return getAnimationSummary();")
                print("\n=== 検出されたアニメーション要素 ===")
                for info in animation_summary:
                    print(f"クラス: {info['class']}")
                    print(f"  アニメーション名: {info['animationName']}")
                    print(f"  Duration: {info['duration']}秒")
                    print(f"  Delay: {info['delay']}秒")

            frames = []
            frame_count = settings.frame_count
            
            if settings.debug_mode:
                print(f"\n=== フレームキャプチャ開始 ===")
                print(f"総フレーム数: {frame_count}")
                print(f"FPS: {settings.fps}")
                print(f"フレーム間隔: {settings.frame_duration_ms}ms")
                print(f"アニメーション時間: {settings.animation_duration}秒")
            
            debug_logs = []
            
            # フレームキャプチャ
            for i in range(frame_count):
                frame_file = temp_frames_dir / f"frame_{i:04d}.png"
                
                # delay時間を考慮したアニメーション進行計算
                total_time = settings.animation_duration + settings.start_delay + settings.end_delay
                time_per_frame = total_time / frame_count
                current_time = i * time_per_frame
                
                # どの段階にあるか判定
                if current_time < settings.start_delay:
                    # 開始delay期間中 - 初期状態を維持
                    progress = 0.0
                elif current_time < settings.start_delay + settings.animation_duration:
                    # アニメーション期間中
                    animation_time = current_time - settings.start_delay
                    progress = animation_time / settings.animation_duration
                else:
                    # 終了delay期間中 - 最終状態を維持
                    progress = 1.0
                
                # JavaScriptでアニメーションの進行状態を設定
                frame_log = driver.execute_script(f"return setAnimationProgress({progress}, {i});")
                
                if settings.debug_mode:
                    debug_logs.append(frame_log)
                    # 詳細デバッグ出力（最初の3フレームと最後の3フレーム、および問題のあるフレーム）
                    if i < 3 or i >= frame_count - 3:
                        print(f"\n--- フレーム {i} ---")
                        print(f"Progress: {progress:.4f}")
                        print(f"Current Time: {frame_log['currentTime']:.4f}秒")
                        for elem in frame_log['elements'][:4]:  # 最初の4要素を表示
                            if 'status' in elem and elem['status'] == 'not_started':
                                print(f"  要素 {elem['class']}: まだ開始していません (delay: {elem['originalDelay']}秒)")
                            else:
                                print(f"  要素 {elem['class']}:")
                                print(f"    元のDelay: {elem['originalDelay']:.2f}秒")
                                print(f"    要素の経過時間: {elem.get('elementTime', 0):.2f}秒")
                                if 'loops' in elem:
                                    print(f"    ループ: {elem['loops']}回目, 進行: {elem.get('progressInLoop', 0):.1%}")
                
                # レンダリング待機
                time.sleep(0.15)
                
                # スクリーンショット保存
                driver.save_screenshot(str(frame_file))
                frames.append(str(frame_file))
                
                progress_percent = int((i + 1) / frame_count * 50)
                self.notify_progress(progress_percent, f"フレーム {i+1}/{frame_count} を生成中...")
            
            # デバッグログをファイルに保存
            if settings.debug_mode:
                debug_log_path = output_dir / f"{Path(settings.gif_output).stem}_debug.json"
                with open(debug_log_path, 'w') as f:
                    json.dump(debug_logs, f, indent=2)
                print(f"\nデバッグログを保存: {debug_log_path}")

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
            
            # フェード効果を適用
            if settings.fade_in_duration > 0 or settings.fade_out_duration > 0:
                self.notify_progress(80, "フェード効果を適用中...")
                images = self._apply_fade_effect(images, settings)
            
            # 実際のフレーム数を確認
            actual_frame_count = len(images)
            
            if settings.debug_mode:
                print(f"\n=== GIF保存情報 ===")
                print(f"指定フレーム数: {frame_count}")
                print(f"実際の画像数: {actual_frame_count}")
                print(f"設定fps: {settings.fps}")
                print(f"フレーム間隔: {duration_ms}ms")
                print(f"期待される総再生時間: {frame_count * duration_ms / 1000:.4f}秒")
            
            # 各フレームの表示時間リストを作成（すべて同じ値）
            durations = [duration_ms] * actual_frame_count
            
            # GIFとして保存
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
            if settings.debug_mode:
                try:
                    with Image.open(gif_path) as check_img:
                        saved_frame_count = 0
                        try:
                            while True:
                                saved_frame_count += 1
                                check_img.seek(check_img.tell() + 1)
                        except EOFError:
                            pass
                        print(f"保存されたGIFのフレーム数: {saved_frame_count}")
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

            self.notify_progress(100, f"変換完了!")
                    
        except Exception as e:
            self.notify_progress(-1, f"エラーが発生しました: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_converting = False
    
    def _apply_fade_effect(self, images: List, settings: ConversionSettings) -> List:
        """各フレームにフェードイン/アウト効果を適用（delay期間も考慮）"""
        total_frames = len(images)
        fps = settings.fps
        
        # 各期間のフレーム数を計算
        start_delay_frames = int(settings.start_delay * fps)
        fade_in_frames = int(settings.fade_in_duration * fps)
        fade_out_frames = int(settings.fade_out_duration * fps)
        end_delay_frames = int(settings.end_delay * fps)
        
        processed_images = []
        for i, img in enumerate(images):
            opacity = 1.0
            
            # どの段階にあるか判定
            if i < start_delay_frames:
                # 開始delay期間中 - 完全透明
                opacity = 0.0
            elif i < start_delay_frames + fade_in_frames:
                # フェードイン期間中
                fade_progress = (i - start_delay_frames) / fade_in_frames
                opacity = fade_progress  # 0.0 から 1.0
            elif i >= total_frames - end_delay_frames:
                # 終了delay期間中 - 完全透明
                opacity = 0.0
            elif i >= total_frames - end_delay_frames - fade_out_frames:
                # フェードアウト期間中
                frames_from_fade_start = i - (total_frames - end_delay_frames - fade_out_frames)
                fade_progress = frames_from_fade_start / fade_out_frames
                opacity = 1.0 - fade_progress  # 1.0 から 0.0
            
            # 不透明度を適用
            if opacity < 1.0:
                # 白背景と合成して透明度効果を実現
                result = Image.new('RGB', img.size)
                result_array = result.load()
                img_array = img.load()
                
                for x in range(img.size[0]):
                    for y in range(img.size[1]):
                        r, g, b = img_array[x, y]
                        # 白（255, 255, 255）に向かってフェード
                        new_r = int(r * opacity + 255 * (1 - opacity))
                        new_g = int(g * opacity + 255 * (1 - opacity))
                        new_b = int(b * opacity + 255 * (1 - opacity))
                        result_array[x, y] = (new_r, new_g, new_b)
                
                processed_images.append(result)
            else:
                processed_images.append(img)
        
        return processed_images

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

        self.title("SVG to GIF Converter ver.1.1.2")
        self.geometry("700x650")
        self.model = ConversionModel()
        self.controller = ConversionController(self.model, self)
        self.model.add_observer(self)
        
        # デフォルトのダウンロードフォルダを設定
        self.default_output_path = str(Path.home() / "Downloads")
        
        # アニメーション時間（検出された値）
        self.animation_duration = 1.65   # デフォルト値
        self.detected_duration = 1.65    # 自動検出された値を保持
        self.is_manual_duration = False  # 手動設定モードのフラグ
        
        self._create_widgets()
        self._setup_layout()
        
    def _create_widgets(self):
        # 入力ファイル選択
        self.file_frame = ttk.LabelFrame(self, text="入力/出力設定", padding=10)
        self.svg_path = tk.StringVar()
        self.output_path = tk.StringVar(value=self.default_output_path)
        self.gif_path = tk.StringVar(value="animation.gif")
        
        # SVG/GIFファイル入力
        ttk.Label(self.file_frame, text="SVGファイル:").grid(row=0, column=0, sticky="w")
        self.svg_entry = ttk.Entry(self.file_frame, textvariable=self.svg_path, width=50)
        self.svg_entry.grid(row=0, column=1, padx=5)
        ttk.Button(self.file_frame, text="参照", command=self._browse_svg).grid(row=0, column=2)
        
        # 出力フォルダ
        ttk.Label(self.file_frame, text="出力フォルダ:").grid(row=1, column=0, sticky="w")
        self.output_entry = ttk.Entry(self.file_frame, textvariable=self.output_path, width=50)
        self.output_entry.grid(row=1, column=1, padx=5, pady=(10, 0))
        ttk.Button(self.file_frame, text="選択", command=self._browse_output_dir).grid(row=1, column=2, pady=(10, 0))
        
        # GIFファイル名入力
        ttk.Label(self.file_frame, text="GIFファイル名:").grid(row=2, column=0, sticky="w")
        self.gif_entry = ttk.Entry(self.file_frame, textvariable=self.gif_path, width=50)
        self.gif_entry.grid(row=2, column=1, padx=5, pady=(10, 0))
        
        # パラメータ設定
        self.param_frame = ttk.LabelFrame(self, text="変換設定", padding=10)
        self.fps = tk.IntVar(value=20)                   # デフォルト20fps
        self.manual_duration = tk.DoubleVar(value=1.65)  # デフォルト1.65秒（小数）
        
        # 左側：アニメーション情報とfps
        left_frame = ttk.Frame(self.param_frame)
        left_frame.grid(row=0, column=0, sticky="nw")
        
        # アニメーション情報表示（青色）
        self.animation_info_label = ttk.Label(left_frame, text="検出されたアニメーション時間: 1.65秒", 
                                             foreground="blue")
        self.animation_info_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        
        self.fps_info_label = ttk.Label(left_frame, text="推奨設定: 20fps", 
                                        foreground="blue")
        self.fps_info_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
        
        # フレームレート設定
        ttk.Label(left_frame, text="フレームレート(fps):").grid(row=2, column=0, sticky="w")
        self.fps_entry = ttk.Entry(left_frame, textvariable=self.fps, width=10)
        self.fps_entry.grid(row=2, column=1, padx=(10, 0))
        self.fps_entry.bind('<KeyRelease>', lambda e: self._on_fps_changed())
        self.fps_entry.bind('<FocusOut>', lambda e: self._on_fps_changed())
        
        # 右側：総再生時間の計算結果
        right_frame = ttk.Frame(self.param_frame)
        right_frame.grid(row=0, column=1, sticky="nw", padx=(50, 0))
        
        # 総再生時間（緑色で表示）
        self.duration_info_label = ttk.Label(right_frame, text="総再生時間: 1.65秒", 
                                            foreground="green")
        self.duration_info_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        
        self.frame_info_label = ttk.Label(right_frame, text="総フレーム数: 33", 
                                         foreground="green")
        self.frame_info_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
        
        # 総再生時間の手動入力
        ttk.Label(right_frame, text="総再生時間(秒):").grid(row=2, column=0, sticky="w")
        self.manual_duration_entry = ttk.Entry(right_frame, textvariable=self.manual_duration, width=10)
        self.manual_duration_entry.grid(row=2, column=1, padx=(10, 0))
        self.manual_duration_entry.bind('<KeyRelease>', lambda e: self._on_manual_duration_changed())
        self.manual_duration_entry.bind('<FocusOut>', lambda e: self._on_manual_duration_changed())
        
        # オプション設定
        self.fade_frame = ttk.LabelFrame(self, text="オプション設定", padding=10)
        self.fade_in = tk.DoubleVar(value=0.0)
        self.fade_out = tk.DoubleVar(value=0.0)
        self.start_delay = tk.DoubleVar(value=0.0)
        self.end_delay = tk.DoubleVar(value=0.0)
        self.debug_mode = tk.BooleanVar(value=False)  # デバッグモード
        
        # 開始前の空白
        ttk.Label(self.fade_frame, text="開始前の空白(秒):").grid(row=0, column=0, sticky="w")
        self.start_delay_entry = ttk.Entry(self.fade_frame, textvariable=self.start_delay, width=10)
        self.start_delay_entry.grid(row=0, column=1, padx=(10, 0))
        self.start_delay_entry.bind('<KeyRelease>', lambda e: self._on_fade_changed())
        self.start_delay_entry.bind('<FocusOut>', lambda e: self._on_fade_changed())
        
        # 終了後の空白
        ttk.Label(self.fade_frame, text="終了後の空白(秒):").grid(row=0, column=2, sticky="w", padx=(30, 0))
        self.end_delay_entry = ttk.Entry(self.fade_frame, textvariable=self.end_delay, width=10)
        self.end_delay_entry.grid(row=0, column=3, padx=(10, 0))
        self.end_delay_entry.bind('<KeyRelease>', lambda e: self._on_fade_changed())
        self.end_delay_entry.bind('<FocusOut>', lambda e: self._on_fade_changed())
        
         # フェードイン
        ttk.Label(self.fade_frame, text="フェードイン(秒):").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.fade_in_entry = ttk.Entry(self.fade_frame, textvariable=self.fade_in, width=10)
        self.fade_in_entry.grid(row=1, column=1, padx=(10, 0), pady=(10, 0))
        self.fade_in_entry.bind('<KeyRelease>', lambda e: self._on_fade_changed())
        self.fade_in_entry.bind('<FocusOut>', lambda e: self._on_fade_changed())
        
        # フェードアウト
        ttk.Label(self.fade_frame, text="フェードアウト(秒):").grid(row=1, column=2, sticky="w", padx=(30, 0), pady=(10, 0))
        self.fade_out_entry = ttk.Entry(self.fade_frame, textvariable=self.fade_out, width=10)
        self.fade_out_entry.grid(row=1, column=3, padx=(10, 0), pady=(10, 0))
        self.fade_out_entry.bind('<KeyRelease>', lambda e: self._on_fade_changed())
        self.fade_out_entry.bind('<FocusOut>', lambda e: self._on_fade_changed())
        
        # デバッグモードチェックボックス
        self.debug_checkbox = ttk.Checkbutton(self.fade_frame, text="デバッグモード", 
                                              variable=self.debug_mode)
        self.debug_checkbox.grid(row=2, column=0, sticky="w", pady=(10, 0))
        
        # SVGスタイル表示（アコーディオン）
        self.style_frame = ttk.Frame(self, padding=10)
        self.style_expanded = False
        self.toggle_style_btn = ttk.Button(self.style_frame, text="▶ SVGスタイル詳細", command=self._toggle_style_view)
        self.toggle_style_btn.pack(anchor="w")
        
        # スタイル表示用のテキストエリア（初期は非表示）
        self.style_text_frame = ttk.Frame(self.style_frame)
        self.style_text = tk.Text(self.style_text_frame, height=6, width=80, wrap=tk.WORD)
        self.style_text.config(state=tk.DISABLED)  # 読み取り専用
        
        # スクロールバー
        self.style_scrollbar = ttk.Scrollbar(self.style_text_frame, orient="vertical", command=self.style_text.yview)
        self.style_text.configure(yscrollcommand=self.style_scrollbar.set)
        
        # 変換ボタンとプログレスバー
        self.control_frame = ttk.Frame(self, padding=10)
        self.reset_btn =   ttk.Button(self.control_frame, text="リセット", command=self._reset_to_auto)
        self.convert_btn = ttk.Button(self.control_frame, text="変換開始", command=self._start_conversion)
        self.progress = ttk.Progressbar(self.control_frame, length=380, mode='determinate')
        self.status_label = ttk.Label(self.control_frame, text="準備完了")
        
    def _setup_layout(self):
        self.file_frame.pack(fill="x", padx=10, pady=5)
        self.param_frame.pack(fill="x", padx=10, pady=5)
        self.fade_frame.pack(fill="x", padx=10, pady=5)
        self.style_frame.pack(fill="x", padx=10, pady=5)  # SVGスタイル表示を追加
        self.control_frame.pack(fill="x", padx=10, pady=5)

        self.status_label.pack(side=tk.LEFT, padx=5, pady=5)
        self.progress.pack(side=tk.LEFT, padx=5, pady=5)
        self.reset_btn.pack(side=tk.LEFT, padx=5, pady=5)
        self.convert_btn.pack(side=tk.LEFT, padx=5, pady=5)
        
        # 初期化処理
        self._update_calculation_display()  # 初期の計算結果を表示
    
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
            
            self._update_calculation_display()
            
        except:
            self.fps.set(20)
            self._on_fps_changed()
    
    def _toggle_style_view(self):
        """SVGスタイル表示のアコーディオン開閉"""
        if self.style_expanded:
            # 折りたたむ
            self.style_text_frame.pack_forget()
            self.toggle_style_btn.config(text="▶ SVGスタイル詳細")
            self.style_expanded = False
        else:
            # 展開する
            self.style_text_frame.pack(fill="both", expand=True, pady=(5, 0))
            self.style_text.pack(side="left", fill="both", expand=True)
            self.style_scrollbar.pack(side="right", fill="y")
            self.toggle_style_btn.config(text="▼ SVGスタイル詳細")
            self.style_expanded = True
    
    def _extract_svg_style(self, svg_content: str) -> str:
        """SVGファイルから<style>タグの内容を抽出"""
        import re
        # <style>タグの内容を抽出
        style_match = re.search(r'<style[^>]*>(.*?)</style>', svg_content, re.DOTALL)
        if style_match:
            return style_match.group(1).strip()
        else:
            # styleタグがない場合、要素のstyle属性を探す
            style_attrs = re.findall(r'style="([^"]+)"', svg_content)
            if style_attrs:
                return "インラインスタイル:\n" + "\n".join(style_attrs)
            return "スタイル情報なし"
    
    def _update_style_display(self, svg_content: str):
        """SVGスタイル表示を更新"""
        style_content = self._extract_svg_style(svg_content)
        
        # テキストエリアを更新
        self.style_text.config(state=tk.NORMAL)
        self.style_text.delete(1.0, tk.END)
        self.style_text.insert(1.0, style_content)
        self.style_text.config(state=tk.DISABLED)
    
    def _on_manual_duration_changed(self):
        """総再生時間の手動入力時の処理"""
        try:
            manual_value = self.manual_duration.get()
            if manual_value > 0:
                # 検出値と異なる値が入力された場合は手動設定モードに
                if abs(manual_value - self.detected_duration) > 0.01:
                    self.animation_duration = manual_value
                    self.is_manual_duration = True
                else:
                    # 検出値と同じ場合は自動設定モードに
                    self.animation_duration = self.detected_duration
                    self.is_manual_duration = False
                self._update_calculation_display()
        except:
            pass  # 無効な入力は無視
    
    def _reset_to_auto(self):
        """自動検出値にリセット"""
        self.is_manual_duration = False
        self.animation_duration = self.detected_duration
        self.manual_duration.set(self.detected_duration)  # 検出値を入力欄に表示
        
        # 表示を更新
        self.animation_info_label.config(text=f"検出されたアニメーション時間: {self.detected_duration:.2f}秒")
        self._update_calculation_display()
    
    def _update_calculation_display(self):
        """計算結果の表示を更新"""
        fps = int(self.fps.get())
        
        # delay時間を含めた総時間を計算
        start_delay = self.start_delay.get()
        end_delay = self.end_delay.get()
        total_animation_time = self.animation_duration + start_delay + end_delay
        
        # 総フレーム数を計算
        total_frames = max(10, int(total_animation_time * fps))
        actual_duration = total_frames / fps
        
        # 表示を更新
        if start_delay > 0 or end_delay > 0:
            self.duration_info_label.config(text=f"総再生時間: {actual_duration:.2f}秒 (delay含む)")
        else:
            self.duration_info_label.config(text=f"総再生時間: {actual_duration:.2f}秒")
        
        self.frame_info_label.config(text=f"総フレーム数: {total_frames}")
    
    def _on_fade_changed(self):
        """フェード設定変更時に情報を更新"""
        try:
            start_delay = self.start_delay.get()
            fade_in = self.fade_in.get()
            fade_out = self.fade_out.get()
            end_delay = self.end_delay.get()
            
            # 総再生時間の再計算
            self._update_calculation_display()
        except:
            pass  # 無効な入力は無視
    
    def _browse_svg(self):
        filename = filedialog.askopenfilename(
            initialdir=self.default_output_path,
            title="SVG/GIFファイルを選択",
            filetypes=[
                ("SVG files", "*.svg"), 
                ("GIF files", "*.gif"),
                ("All files", "*.*")
            ]
        )
        if filename:
            self.svg_path.set(filename)
            self._on_file_selected()
    
    def _browse_output_dir(self):
        """出力フォルダを選択"""
        dirname = filedialog.askdirectory(
            initialdir=self.output_path.get() or self.default_output_path,
            title="出力フォルダを選択"
        )
        if dirname:
            self.output_path.set(dirname)
    
    def _on_file_selected(self):
        """SVG/GIFファイルが選択されたときの処理"""
        file_path = self.svg_path.get()
        if file_path and os.path.exists(file_path):
            file_extension = Path(file_path).suffix.lower()
            
            # ファイル名からGIFファイル名を生成
            filename_stem = Path(file_path).stem
            
            if file_extension == '.gif':
                # GIFファイルの場合はそのまま使用
                self.gif_path.set(f"{filename_stem}.gif")
            else:
                # SVGファイルの場合は新しいGIFファイル名を生成
                gif_name = f"{filename_stem}.gif" if not filename_stem.endswith('.gif') else filename_stem
                self.gif_path.set(gif_name)
            
            # 自動設定を実行
            self._auto_configure()
            
    def _auto_configure(self):
        """ファイルを解析して最適な設定を自動適用（SVG/GIF対応）"""
        file_path = self.svg_path.get()
        if not file_path or not os.path.exists(file_path):
            return
        
        file_extension = Path(file_path).suffix.lower()
        animation_duration, fps = self.controller.analyze_svg(file_path)
        
        # 検出された値を保存
        self.detected_duration = animation_duration
        
        # 手動設定モードでない場合のみ、自動検出値を適用
        if not self.is_manual_duration:
            self.animation_duration = animation_duration
            self.manual_duration.set(animation_duration)  # 自動検出値を入力欄に表示
        
        self.fps.set(int(fps))
        
        # SVGファイルの場合、スタイル情報を表示
        if file_extension == '.svg':
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()
                self._update_style_display(svg_content)
            except Exception as e:
                print(f"SVGスタイル読み込みエラー: {e}")
        
        # ファイル種別に応じて表示を更新
        if file_extension == '.gif':
            # GIFファイルの情報を表示
            duration, frame_count, actual_fps = self.model.get_gif_info(file_path)
            self.animation_info_label.config(text=f"GIF総再生時間: {duration:.2f}秒")
            self.fps_info_label.config(text=f"GIFフレームレート: {actual_fps:.1f}fps")
        else:
            # SVGファイルの情報を表示
            if self.is_manual_duration:
                self.animation_info_label.config(text=f"総再生時間: {self.animation_duration:.2f}秒 (手動設定)")
            else:
                self.animation_info_label.config(text=f"検出されたアニメーション時間: {animation_duration:.2f}秒")
            self.fps_info_label.config(text=f"推奨設定: {fps}fps")
        
        # 計算結果を更新
        self._update_calculation_display()
            
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
            animation_duration=self.animation_duration,
            fade_in_duration=self.fade_in.get(),
            fade_out_duration=self.fade_out.get(),
            start_delay=self.start_delay.get(),
            end_delay=self.end_delay.get(),
            debug_mode=self.debug_mode.get()
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