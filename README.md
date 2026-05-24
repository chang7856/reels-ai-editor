# Reels AI Editor

本機 GUI 工具，用來上傳原始影片，自動剪掉停頓、產生繁中/英文字幕、輸出 IG Reels 等級的壓縮影片，並產生封面圖。

A local GUI tool for uploading raw footage, automatically removing pauses, adding Traditional Chinese/English subtitles, exporting an Instagram Reels-ready compressed video, and generating a cover image.

## 功能 / Features

- 上傳 MOV / MP4 / M4V / AVI 影片
- 自動偵測並剪掉停頓
- 使用 Whisper 轉錄中文並翻譯英文
- 燒錄繁中 + 英文雙語字幕
- 套用 IG Reels 安全區，避免標題與字幕被介面遮住
- 輸出 720 x 1280 的壓縮 Reels MP4
- 自動產生白字 + 黃字風格封面
- GUI 支援中文 / English 切換

- Upload MOV / MP4 / M4V / AVI videos
- Automatically detect and remove pauses
- Transcribe Chinese and translate English with Whisper
- Burn in Traditional Chinese + English subtitles
- Use Instagram Reels safe areas for title and subtitles
- Export a compressed 720 x 1280 Reels MP4
- Generate a bold white + yellow cover image
- Switch the GUI between Chinese and English

## 啟動 / Run

```bash
python3 app.py
```

Then open:

```text
http://127.0.0.1:5057
```

macOS users can also double-click:

```text
start_reels_gui.command
```

## 使用方式 / How To Use

1. 開啟 GUI。
2. 上傳原始影片。
3. 點「開始自動剪輯」。
4. 等待處理完成。
5. 開啟或下載輸出的 Reels 影片與封面。

1. Open the GUI.
2. Upload raw footage.
3. Click "Start Auto Edit".
4. Wait for processing to finish.
5. Open or download the exported Reels video and cover.

## 輸出 / Outputs

每次任務會建立在 `outputs/<job-id>/`：

Each job is written to `outputs/<job-id>/`:

- `reels_ig_compressed.mp4`: IG Reels 壓縮影片 / compressed IG Reels video
- `reels_cover.jpg`: 封面圖 / cover image
- `subtitles.ass`: 字幕檔 / subtitle file
- `result.json`: 任務結果 / job metadata
- `run.log`: 處理紀錄 / processing log

## 程式記憶 / Editing Memory

偏好設定寫在：

Preferences are saved in:

```text
reels_memory.json
```

目前包含：

Current saved preferences include:

- 標題：`POV：全自動化 AI 小編跟廣告`
- 字幕：繁中 + 英文、置中、安全區
- 中文字距放鬆
- 英文比中文小，但不過小
- 直接輸出手機好傳的 IG Reels 壓縮版
- 產生白字 + 黃字封面
- 剪停頓，但不過度重寫故事
- 保留結尾「掰掰」

- Title: `POV：全自動化 AI 小編跟廣告`
- Subtitles: Traditional Chinese + English, centered, safe area
- More comfortable Chinese character spacing
- English subtitles smaller than Chinese, but still readable
- Direct Instagram Reels-ready compressed export
- Bold white + yellow cover style
- Remove pauses without over-rewriting the story
- Keep the ending "bye"

## 需求 / Requirements

- Python 3
- FFmpeg
- Flask
- faster-whisper
- OpenCC
- Pillow

Install Python dependencies:

```bash
pip install flask faster-whisper opencc-python-reimplemented pillow
```

Install FFmpeg on macOS:

```bash
brew install ffmpeg
```

## 注意 / Notes

這是本機工具，影片會存在你的電腦裡，不會自動上傳到外部服務。

This is a local tool. Videos stay on your computer and are not uploaded to any external service automatically.
