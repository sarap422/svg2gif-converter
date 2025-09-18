# SVG to GIF Converter

SVGアニメーションをGIFアニメーションに変換するPythonツールです。特に、複数の要素が時間差で動く「順番アニメーション」を再現できます。

## 主な特徴

- **順番アニメーション対応**: CSS `animation-delay` を解析し、要素が順番に動くアニメーションを再現
- **fps制御**: フレームレートのみで滑らかさを制御、フレーム数は自動計算
- **自動設定**: SVGファイルを解析して最適なfpsを自動提案
- **高品質出力**: 2倍解像度でキャプチャしてクリアなGIFを生成
- **GUI操作**: tkinterベースの直感的なインターフェース

## 動作環境

- **Python**: 3.7以上
- **OS**: Windows 10/11, macOS 10.14+, Linux (Ubuntu 18.04+)
- **ブラウザ**: Google Chrome または Chromium

## インストール手順

### ステップ1: リポジトリの取得
```bash
git clone https://github.com/sarap422/svg2gif-converter.git
cd svg2gif-converter
```

### ステップ2: 仮想環境の作成（推奨）
```bash
# 仮想環境を作成
python -m venv venv

# 仮想環境をアクティベート
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### ステップ3: 依存関係のインストール

**重要**: Windowsで `pip` エラーが発生する場合は `python -m pip` を使用してください。

```bash
# 通常のインストール（推奨）
python -m pip install pillow selenium webdriver-manager

# requirements.txtを使用する場合
python -m pip install -r requirements.txt
```

#### Windowsで `pip` エラーが発生する場合

以下のようなエラーが出る場合：
```
Fatal error in launcher: Unable to create process using '"C:\Python\Python312\python.exe" "C:\Python\Python312\Scripts\pip.exe" install': ????
```

**解決方法**:
1. `python -m pip` を使用（最も確実）
2. 仮想環境を新しく作り直す
3. pipを最新版に更新

```bash
# 解決策1: python -m pip を使用
python -m pip install pillow selenium webdriver-manager

# 解決策2: 仮想環境を作り直し
deactivate
rmdir /s venv
python -m venv venv
venv\Scripts\activate
python -m pip install pillow selenium webdriver-manager

# 解決策3: pipの修復
python -m pip install --upgrade pip
```

### ステップ4: 動作確認
```bash
# ライブラリが正常にインストールされているか確認
python -c "import PIL, selenium, webdriver_manager; print('インストール成功！')"
```

## 使い方

### 基本操作
1. **ツール起動**
   ```bash
   python svg2gif-converter.py
   ```

2. **SVGファイル選択**
   - 「参照」ボタンでSVGファイルを選択
   - アニメーション情報が自動検出されます

3. **設定確認**
   - 「最適値を自動設定」で推奨設定を適用
   - フレームレート(fps)で滑らかさを調整

4. **変換実行**
   - 「変換開始」ボタンをクリック
   - 完成したGIFがダウンロードフォルダに保存されます

### 設定パラメーター

#### フレームレート(fps): 5-30fps
- **5-10fps**: カクカクした動き（軽量）
- **15-20fps**: 標準的な滑らかさ（推奨）
- **25-30fps**: 非常に滑らか（高品質）

#### 自動計算される値
- **総フレーム数**: アニメーション時間 × fps
- **総再生時間**: フレーム数 ÷ fps

#### 計算例（blocks-scale-black-36.svg）
```
検出時間: 1.65秒
20fps設定 → 33フレーム、1.65秒再生
30fps設定 → 49フレーム、1.63秒再生（より滑らか）
```

## 対応するアニメーション形式

### ✅ 対応済み
- **CSSアニメーション**: `@keyframes` + `animation`
- **順番アニメーション**: `animation-delay` による時間差
- **SMIL**: `<animate>`, `<animateTransform>`

### ❌ 非対応
- **JavaScript**: 動的制御アニメーション
- **インタラクティブ**: ホバーやクリックイベント
- **外部依存**: 外部ファイルへの参照

## トラブルシューティング

### よくある問題

#### 1. Windowsでのpipエラー
```bash
# エラー: Fatal error in launcher または文字化け
# 解決: python -m pip を使用
python -m pip install pillow selenium webdriver-manager
```

#### 2. Chrome/ChromeDriverの問題
```bash
# ChromeDriverは自動ダウンロードされますが、エラーの場合：
# Chromeブラウザがインストールされているか確認
# 最新版に更新してください
```

#### 3. 変換が途中で停止
```bash
# ブラウザプロセスが残っている場合
# Windows:
taskkill /f /im chrome.exe /im chromedriver.exe

# macOS/Linux:
pkill -f chrome
pkill -f chromedriver
```

#### 4. メモリ不足エラー
- フレームレートを下げる（30fps → 20fps）
- 大きなSVGファイルの場合は分割処理を検討

#### 5. アニメーションが正しく変換されない
- SVGファイルをブラウザで開いて動作確認
- CSS `animation-duration` と `animation-delay` が正しく設定されているか確認

### パフォーマンス最適化

#### 推奨設定
```
一般的なアニメーション: 20fps
高品質が必要な場合: 30fps
ファイルサイズ重視: 15fps
```

#### システム要件
```
RAM: 4GB以上推奨（高fpsの場合は8GB以上）
ストレージ: 一時ファイル用に1GB以上の空き容量
CPU: 変換時間に影響（高性能ほど高速）
```

## 技術仕様

### アーキテクチャ
- **MVCパターン**: Model-View-Controller設計
- **非同期処理**: UIをブロックしない変換処理
- **自動リソース管理**: 一時ファイルの自動削除

### 主要技術
1. **Selenium WebDriver**: SVGアニメーションキャプチャ
2. **Pillow (PIL)**: 画像処理とGIF生成
3. **正規表現**: SVGアニメーション情報解析
4. **JavaScript注入**: ブラウザでのアニメーション制御

### 出力設定
```python
# GIF最適化設定
optimize=False      # フレーム数保持のため無効
disposal=2          # 完全なフレーム置き換え
loop=0              # 無限ループ
```

## 更新履歴

### ver.0.1.0 (最新)
- fps制御に変更（フレーム数は自動計算）
- 総再生時間と総フレーム数の自動表示
- 時間ベースの進行計算で再生速度を修正
- Windowsでのpip問題に対応したドキュメント

### ver.0.0.9
- 順番アニメーション制御の完全実装
- フレーム数保持の確実な動作

### ver.0.0.1-0.0.8
- 基本機能の実装と改良
- UI改善とエラーハンドリング強化

## ライセンス

MIT License - 詳細は [LICENSE](LICENSE) を参照

---



