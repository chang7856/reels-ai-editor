# Reels AI Editor

**Drop a talking-head video in. Get a vertical IG Reel out — pauses cut, captions burned in, cover designed.**

把對著鏡頭講話的影片丟進去，自動剪停頓、燒字幕、產生封面，輸出 IG 直式 Reels。

> 中文版說明往下捲，跳到 **[中文使用說明](#中文使用說明)**

---

## What it does (English)

- ✂️ Removes silent pauses automatically with `silencedetect`
- 🎙️ Transcribes with [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (`small` model, runs on CPU)
- 🌏 Bilingual subtitles (ZH+EN) on the **Chinese page**, English-only on the **English page**
- 🖼️ Three cover styles: **Editorial Bold / All-White Hook / Color Pop**
- 📐 Output is always **720×1280 vertical MP4**, IG Reels safe-area aware
- 🗑️ Your footage is deleted **15 minutes** after upload — nothing is kept on the server

### Scope

This tool is built for **a single person talking to camera** (interview / vlog / piece-to-camera). It will not edit:

- Multi-cam footage
- Music-video / B-roll heavy edits
- Horizontal / square output

If you have any of those, this is not the tool for you.

---

## Choose your install path

| Who are you? | Take this path |
|---|---|
| 🐭 I just want to use it, I don't code | **Path A — Download the .app** |
| 🌐 I'll use the public link my friend shared | Just open the URL, that's it |
| 🛠️ I'm a developer, I want to run from source | **Path B — Run from source** |

---

## Path A — Download the .app (no coding needed)

### 1. Install ffmpeg (one-time, ~30 seconds)

The app needs `ffmpeg` to read your video. Install it once and you never have to think about it again.

**macOS:**
1. Open Terminal (⌘+Space → type "terminal")
2. Paste this and press Enter:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install ffmpeg
   ```
   (First line installs [Homebrew](https://brew.sh) if you don't have it; second line installs ffmpeg.)

**Windows:**
- Open PowerShell as administrator and run:
  ```powershell
  winget install ffmpeg
  ```

### 2. Download the right .app for your machine

Go to the [**Releases**](../../releases/latest) page and grab one of:

| File | For |
|---|---|
| `ReelsAIEditor-macOS-arm64.dmg` | **Mac with M1/M2/M3/M4** (Apple Silicon, 2020+) |
| `ReelsAIEditor-macOS-intel.dmg` | **Mac with Intel chip** (pre-2020) |
| `ReelsAIEditor-Windows-x64.zip` | **Windows 10/11** |

Not sure which Mac you have? Click 🍎 → "About This Mac" → look at "Chip". If it says "M-something", grab the **arm64** one.

### 3. Open the app

**Mac:** Double-click the `.dmg`, drag `ReelsAIEditor` to your Applications folder, then open it.

> First time you open it, macOS will say "ReelsAIEditor cannot be opened because the developer cannot be verified". This is normal — I didn't pay Apple $99/yr. To get past it:
> 1. Right-click `ReelsAIEditor` → "Open"
> 2. Click "Open" in the warning dialog
> Mac will remember this choice.

**Windows:** Unzip, double-click `ReelsAIEditor.exe`.

### 4. Drop a video in

Your browser will open at `http://127.0.0.1:5057`. Pick a Cover Style, drag your video, click **Start Auto Edit**. Wait ~1 minute. Download.

---

## Path B — Run from source (developers)

```bash
git clone https://github.com/<you>/reels-ai-editor.git
cd reels-ai-editor
brew install ffmpeg                  # macOS  (Linux: sudo apt install ffmpeg)
pip3 install -r requirements.txt
python3 app.py
```

Open <http://127.0.0.1:5057> in your browser.

---

## Share the app with people who don't have it (free)

You can expose your local server as a public URL using **Cloudflare Tunnel**. Anyone can use it without installing anything — they just open the link.

```bash
brew install cloudflared
./share-tunnel.command
```

`share-tunnel.command` will:
1. Start the Flask app
2. Start a Cloudflare Tunnel
3. Print + copy the public `https://xxxxx.trycloudflare.com` URL to your clipboard

Send that URL to anyone. As long as your computer is awake, they can upload videos. Files still auto-delete after 15 minutes, so you don't accumulate footage on your machine.

**Disk usage on your machine:**
- Always-on: ~1.2 GB (Whisper model + ffmpeg + Python deps)
- Per active job: 100–500 MB temporary (deleted after 15 min)
- 5 simultaneous users peak: ~3 GB

---

## Privacy

- Your video lives on the computer that's running this app — **never uploaded anywhere else**
- It's **deleted automatically 15 minutes after upload**
- Logs are wiped at the same time
- File-extension whitelist (only `.mp4 / .mov / .m4v`), filenames are sanitised

If you're running the app on your own Mac, "the computer" is your Mac. If you're using a friend's public Cloudflare Tunnel link, "the computer" is theirs — so trust them like you trust your friend.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| App won't start, terminal says **"Missing: ffmpeg, ffprobe"** | Run `brew install ffmpeg` (macOS) / `winget install ffmpeg` (Win) |
| Browser opens but page doesn't load | Port 5057 might be busy — quit other instances or restart your Mac |
| "Cannot be opened because developer cannot be verified" | Right-click the app → Open (one-time bypass) |
| Upload fails with "影片格式無法讀取" | Re-export your video to `.mp4` (most editors do this by default) |
| Transcription is slow on Intel Mac | Yep, Apple Silicon is 3–5× faster on Whisper. Use the M-chip Mac if you have one |
| Whisper downloads 400 MB on first run | Normal. Only happens once, model is cached |

---

## 中文使用說明

### 它做什麼

- ✂️ 自動剪掉影片裡的停頓
- 🎙️ 用 `faster-whisper` 做語音轉文字（CPU 跑 small 模型）
- 🌏 中文版輸出 **繁中＋英文** 雙語字幕、英文版只輸出 **English**
- 🖼️ 三種封面樣式：**雜誌大標 / 全白爆點 / 繽紛大字**
- 📐 一律輸出 **720×1280 直式 MP4**，文字位置自動避開 IG Reels 介面
- 🗑️ 影片 **上傳後 15 分鐘自動刪除**，這台電腦上不留檔

### 使用範圍

只適合「**一個人對著鏡頭講話**」的影片（訪談、Vlog、口播）。下面這幾種**不支援**：

- 多機位剪輯
- 音樂 MV / 大量 B-roll 剪接
- 橫式 / 方形輸出

### 怎麼安裝

| 你是誰？ | 走哪條 |
|---|---|
| 🐭 我只想用，我不會寫程式 | **路 A：下載 .app** |
| 🌐 朋友丟我一個網址讓我用 | 點網址，就這樣 |
| 🛠️ 我會 Python，想看原始碼 | **路 B：從原始碼跑** |

### 路 A：下載 .app

#### 1. 先裝 ffmpeg（一次就好）

**macOS：**
1. 打開「終端機」（⌘ + 空白鍵搜尋 "terminal"）
2. 貼上這兩行：
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install ffmpeg
   ```

**Windows：** 以系統管理員開 PowerShell：
```powershell
winget install ffmpeg
```

#### 2. 下載對應你 Mac/PC 的版本

到 [**Releases**](../../releases/latest) 頁面下載：

| 檔案 | 適用 |
|---|---|
| `ReelsAIEditor-macOS-arm64.dmg` | **Mac 是 M1/M2/M3/M4** |
| `ReelsAIEditor-macOS-intel.dmg` | **Mac 是 Intel 處理器**（2020 之前） |
| `ReelsAIEditor-Windows-x64.zip` | **Windows 10/11** |

不知道你 Mac 是哪一種？點左上 🍎 → 「關於這台 Mac」→ 看「晶片」。寫 M 開頭就是 **arm64**。

#### 3. 打開 App

**Mac：** 雙擊 `.dmg`，把 `ReelsAIEditor` 拖到「應用程式」資料夾，然後打開它。

> 第一次打開 macOS 會擋你說「無法打開，因為無法驗證開發者」。這是正常的（因為我沒給 Apple $99/年）。解法：
> 1. 對著 App 按右鍵 → 「打開」
> 2. 跳出警告再按一次「打開」
> 以後它會記得，不會再擋。

**Windows：** 解壓縮，雙擊 `ReelsAIEditor.exe`。

#### 4. 丟影片進去

瀏覽器會打開 `http://127.0.0.1:5057`。挑一個封面樣式 → 拖影片 → 按「**開始自動剪輯**」→ 等大概 1 分鐘 → 下載。

### 路 B：從原始碼跑

```bash
git clone https://github.com/<你>/reels-ai-editor.git
cd reels-ai-editor
brew install ffmpeg                  # macOS
pip3 install -r requirements.txt
python3 app.py
```

打開瀏覽器到 <http://127.0.0.1:5057>。

### 把 App 分享給沒裝的人用（免費）

用 **Cloudflare Tunnel** 把你電腦上的 app 變成一條公開網址，朋友直接點網址就能用，他不用裝任何東西。

```bash
brew install cloudflared
./share-tunnel.command
```

`share-tunnel.command` 會：
1. 啟動 Flask
2. 啟動 Cloudflare Tunnel
3. 把公開網址（`https://xxxxx.trycloudflare.com`）印出來並複製到剪貼簿

把那條網址貼給朋友。只要你電腦沒睡著他就能用。影片仍會 15 分鐘自動刪除，所以你電腦不會被別人塞滿。

**電腦容量會用多少？**
- 常駐：約 **1.2 GB**（Whisper model + Python 套件 + ffmpeg）
- 每支處理中影片：100–500 MB（15 分鐘後清掉）
- 5 個人同時跑的尖峰：~3 GB

### 隱私

- 影片只存在跑 app 的這台電腦上，**不會傳到外面**
- 上傳後 **15 分鐘自動刪除**
- log 也一起刪
- 只接受 `.mp4 / .mov / .m4v`，檔名會清掉特殊字元

如果是你自己 Mac 跑，「這台電腦」就是你的 Mac。如果是用朋友的 Cloudflare Tunnel 網址，「這台電腦」是他的，所以信任程度等於你信任你朋友。

### 卡住了怎麼辦

| 症狀 | 解法 |
|---|---|
| 開不起來，Terminal 跳「Missing: ffmpeg」 | `brew install ffmpeg`（Mac）/ `winget install ffmpeg`（Win） |
| 瀏覽器有開但網頁打不開 | port 5057 被佔了，重開機或關掉其他程式 |
| 「無法打開，開發者未驗證」 | 右鍵 App → 打開（一次性允許） |
| 上傳跳「影片格式無法讀取」 | 重新匯出成 `.mp4`，大部分剪輯軟體預設都是這個 |
| Intel Mac 轉錄超慢 | 對，Apple Silicon 跑 Whisper 快 3–5 倍。有 M 系列就用 M 系列 |
| 第一次啟動下載了 400 MB | 正常，那是 Whisper model，下載一次就好 |

---

## Last Update

2026.05

## License

[MIT](LICENSE) — do whatever you want, but I'm not responsible for what you do with it.

## Credits

Built by **Jessie D. Chang** ([LinkedIn](https://www.linkedin.com/in/taofang-chang)) with the help of Claude.

Speech recognition: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
Traditional Chinese conversion: [OpenCC](https://github.com/yichen0831/opencc-python)
