# Reels AI Editor

**Drop a talking-head video in. Get a vertical IG Reel out — pauses cut, captions burned in, cover designed.**

把對著鏡頭講話的影片丟進去，自動剪停頓、燒字幕、產生封面，輸出 IG 直式 Reels。

## ⬇️ 直接下載 / Direct download

[![Download macOS Apple Silicon](https://img.shields.io/badge/macOS-Apple%20Silicon%20.dmg-blue)](https://github.com/chang7856/reels-ai-editor/releases/download/v1.1.0/ReelsAIEditor-macOS-arm64.dmg)
[![Download macOS Intel](https://img.shields.io/badge/macOS-Intel%20.dmg-blue)](https://github.com/chang7856/reels-ai-editor/releases/download/v1.1.0/ReelsAIEditor-macOS-intel.dmg)
[![Download Windows](https://img.shields.io/badge/Windows-x64%20.zip-blueviolet)](https://github.com/chang7856/reels-ai-editor/releases/download/v1.1.0/ReelsAIEditor-Windows-x64.zip)

往下看「中文 — 安裝跟使用」就有一步一步教學。

## 💻 需要什麼 / System requirements

| | Mac (Apple Silicon) | Mac (Intel) | Windows |
|---|---|---|---|
| **作業系統 OS** | macOS 12+ | macOS 12+ | Windows 10 / 11 |
| **記憶體 RAM** | 8 GB+ | 8 GB+ | 8 GB+ |
| **磁碟空間 Disk** | 3 GB | 3 GB | 3 GB |
| **網路 Network** | 首次需要（下載模型 1.5 GB）/ Internet on first run only | 同 | 同 |
| **3 分鐘影片處理時間 / 3-min clip wall time** | **~2.5 分鐘** (MLX + ANE) | ~8-10 分鐘 (CPU fallback) | ~8-10 分鐘 (CPU fallback) |
| **瀏覽器 Browser** | Safari 14+ / Chrome 100+ | 同 | Chrome 100+ / Edge 100+ |

> ⚠️ **Intel Mac 跟 Windows 跑會慢 3-5×**（沒有 Apple Neural Engine 加速）。要快就用 Apple Silicon。

---

> 📘 中文使用者：直接看下面「中文 — 安裝跟使用」就好。
>
> 📗 English readers: scroll past the Chinese block to **[English — install & daily use](#english--install--daily-use)**.

---

## 中文 — 安裝跟使用

下面這段是給「**完全沒做過開發、第一次看 GitHub 也不知道是什麼**」的人看的。

### 🍎 在 Mac 上裝（一輩子只做一次）

1. 到 [**Releases**](../../releases/latest) 頁面，下載對應你 Mac 的檔案：
   - **Mac 是 M1 / M2 / M3 / M4**（2020 年後的）→ 抓 `ReelsAIEditor-macOS-arm64.dmg`
   - **Mac 是 Intel 處理器**（2020 年前的）→ 抓 `ReelsAIEditor-macOS-intel.dmg`
   - 不確定？點左上角 🍎 →「關於這台 Mac」→ 看「晶片」欄。寫 M 開頭就是 arm64
2. **雙擊** 剛下載的 `.dmg`
3. Finder 跳出一個小視窗，裡面有 ReelsAIEditor 圖示。**把它拖到旁邊的「應用程式」（Applications）資料夾**
4. 視窗右上角 X 關掉。Desktop 上的灰色磁碟圖示，按右鍵 → 退出
5. **打開「終端機」**：⌘ + 空白鍵搜尋 `Terminal`，按 Enter
6. 把下面這行**整段複製、貼進去、按 Enter**：

   ```bash
   xattr -dr com.apple.quarantine /Applications/ReelsAIEditor.app
   ```

7. 看起來沒反應就是成功了（Mac 的習慣：成功就靜悄悄）
8. 關掉終端機。**整輩子不用再開了。**

> 為什麼要這一步？因為我沒給 Apple 每年 $99 美金當註冊開發者，所以 Mac 預設會擋。這行指令對 Mac 任何使用者都有效，不需要密碼，不會動到別的東西，只是告訴 Mac「這個 App 我自己下載的，別擋」。

### 🖱️ 每次要剪片的時候

跟用一般 App 一樣，**就點 .app 圖示**：

1. 從以下任一處點 **ReelsAIEditor** 圖示：
   - Launchpad 的 App 列表
   - Finder → 應用程式 → 雙擊 `ReelsAIEditor`
   - Spotlight（⌘ + 空白鍵）→ 打 `reels` → Enter
2. 瀏覽器會**自動跳出** `http://127.0.0.1:5057/`
3. 把影片拖進去 → 等剪好 → 下載
4. 用完直接關瀏覽器分頁就好

> 不小心關掉分頁但 App 還沒關？瀏覽器網址列打 `127.0.0.1:5057` 就回來。
> 重開機、關機後，再點一次 .app 圖示就好，**不用再跑 xattr**。

### 🪟 在 Windows 上裝（更簡單）

1. 下載 `ReelsAIEditor-Windows-x64.zip`
2. 解壓縮
3. 雙擊 `ReelsAIEditor.exe`
4. Windows 可能會跳「Windows 已保護您的電腦」→ 點「**其他資訊**」→「**仍要執行**」
5. 之後瀏覽器自動開啟 → 把影片拖進去

每次要剪：雙擊 `ReelsAIEditor.exe`。

### ⚠️ 第一次跑會等 1.5 GB 模型下載

第一支影片剪的時候，會多花 30-60 秒下載語音辨識模型（約 1.5 GB）。**只下載這一次**，之後永久 cache。

---

## English — install & daily use

This section is for **first-time users who don't know what GitHub is, have never seen Terminal, and just want the thing to work**.

### 🍎 Install on Mac (one-time, ever)

1. Go to [**Releases**](../../releases/latest) and download the file for your Mac:
   - **Mac with M1 / M2 / M3 / M4** (2020 onwards) → grab `ReelsAIEditor-macOS-arm64.dmg`
   - **Mac with Intel chip** (pre-2020) → grab `ReelsAIEditor-macOS-intel.dmg`
   - Not sure? Top-left 🍎 → "About This Mac" → look at "Chip". If it says "M-something", you're on arm64.
2. **Double-click** the downloaded `.dmg`
3. A Finder window pops up with the `ReelsAIEditor` icon. **Drag it into the `Applications` folder next to it.**
4. Close the window. Right-click the grey disk on your Desktop → Eject.
5. **Open Terminal**: ⌘ + Space → type `Terminal` → Enter
6. Copy the line below, **paste it into Terminal, hit Enter**:

   ```bash
   xattr -dr com.apple.quarantine /Applications/ReelsAIEditor.app
   ```

7. No output = success (Mac convention: silence is good)
8. Close Terminal. **You'll never need to touch it again.**

> Why this step? I haven't paid Apple's \$99 / year developer fee, so macOS Gatekeeper blocks the app by default. This one-liner works for any Mac user — no password, no system change, just tells macOS "I downloaded this myself, don't block it."

### 🖱️ Daily use — every time you want to edit

Treat it like any other app: **click the icon**.

1. Launch **ReelsAIEditor** from any of these:
   - Launchpad's app grid
   - Finder → Applications → double-click `ReelsAIEditor`
   - Spotlight (⌘ + Space) → type `reels` → Enter
2. Your browser **auto-opens** `http://127.0.0.1:5057/`
3. Drop a video in → wait → download
4. When done, just close the browser tab

> Accidentally closed the tab but app's still running? Type `127.0.0.1:5057` in your browser's address bar.
> After a reboot, just click the .app icon again — **you don't need to re-run the xattr command**.

### 🪟 Install on Windows (easier)

1. Download `ReelsAIEditor-Windows-x64.zip`
2. Unzip
3. Double-click `ReelsAIEditor.exe`
4. Windows might pop up "Windows protected your PC" → click **More info** → **Run anyway**
5. Browser opens → drag your video in

Each subsequent use: double-click `ReelsAIEditor.exe`.

### ⚠️ First run downloads a 1.5 GB model

The very first video takes 30-60 seconds longer because it downloads the speech-recognition model (~1.5 GB). **Once only** — cached forever after.

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

## What it does (technical summary)

(Install + daily-use steps are in the bilingual section above.)

All three platform builds are actively maintained from v1.1 onwards. See
[RELEASES.md](RELEASES.md) for the version-by-version changelog.

| File | For |
|---|---|
| `ReelsAIEditor-macOS-arm64.dmg` | Mac with M1/M2/M3/M4 (Apple Silicon, 2020+) |
| `ReelsAIEditor-macOS-intel.dmg` | Mac with Intel chip (pre-2020) |
| `ReelsAIEditor-Windows-x64.zip` | Windows 10/11 |

---

## Share the app with people who don't have it (free)

You can expose your local server as a public URL using **Cloudflare Tunnel**. Anyone can use it without installing anything — they just open the link.

This is the one bit that does need a Terminal step, and it's optional — only do this if you actually want to share. Install `cloudflared` once, then double-click `share-tunnel.command` from the unzipped repo and it will:

1. Start the Flask app
2. Start a Cloudflare Tunnel
3. Print + copy the public `https://xxxxx.trycloudflare.com` URL to your clipboard

Send that URL to anyone. As long as your computer is awake, they can upload videos. Files still auto-delete after 15 minutes, so you don't accumulate footage on your machine.

**Disk usage on your machine:**
- Always-on: ~1.3 GB (Whisper model + the .app itself, which has ffmpeg bundled)
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

## 🆘 卡住了怎麼辦 / If something breaks

**1. 看 job log（最直接）/ Read the job log first**

Mac:
```bash
ls -t ~/Library/Application\ Support/ReelsAIEditor/outputs 2>/dev/null || \
  ls -t /Applications/ReelsAIEditor.app/Contents/Frameworks/outputs
```
找最新那個資料夾，裡面 `run.log` 就是錯誤訊息。/ Find the newest folder; `run.log` inside has the full error.

Windows: `Documents\ReelsAIEditor\outputs\<最新 job>\run.log`

**2. 把 `run.log` 跟描述貼到 GitHub Issues / Open an issue with the log:**

👉 [github.com/chang7856/reels-ai-editor/issues/new](https://github.com/chang7856/reels-ai-editor/issues/new)

**3. 常見問題快查表 / Quick reference table:**

| Symptom | Fix |
|---|---|
| 第一次跑卡在 "正在載入 Whisper"（10 分鐘以上）/ Stuck on "Loading Whisper" for 10+ min | 沒網路或被 HuggingFace 限速；確認網路後重試 / No internet, or HF rate-limit — check connection and retry |
| Browser opens but page doesn't load | Port 5057 might be busy — quit other instances or restart your Mac |
| "Cannot be opened because developer cannot be verified" | 跑那行 `xattr -dr com.apple.quarantine /Applications/ReelsAIEditor.app`（看本頁最上面）|
| Upload fails with "影片格式無法讀取" | Re-export your video to `.mp4` (most editors do this by default) |
| Transcription is slow on Intel Mac / Windows | 預期行為：沒有 ANE，會走 CPU fallback，慢 3-5× / Expected — no Apple Neural Engine, CPU fallback is 3-5× slower |
| 第一次跑下載 1.5 GB / First run downloads 1.5 GB | Normal. Only happens once, model is cached |
| App is corrupted / missing files on first run | Re-download the .dmg from the [Releases](../../releases/latest) page — the bundle ships with ffmpeg + ffprobe inside |

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

### 怎麼安裝 + 怎麼用

**請看本頁最上面的「中文 — 安裝跟使用」段落**。Mac 一輩子做一次的 `xattr` 指令、每次怎麼用、Windows 怎麼裝，全部都寫在那邊。

### 把 App 分享給沒裝的人用（免費）

用 **Cloudflare Tunnel** 把你電腦上的 app 變成一條公開網址，朋友直接點網址就能用，他不用裝任何東西。

這一段是少數需要開終端機的步驟，而且**只有想分享給朋友**才需要做。先裝一次 `cloudflared`，然後從你下載的 repo 資料夾雙擊 `share-tunnel.command`，它會：

1. 啟動 Flask
2. 啟動 Cloudflare Tunnel
3. 把公開網址（`https://xxxxx.trycloudflare.com`）印出來並複製到剪貼簿

把那條網址貼給朋友。只要你電腦沒睡著他就能用。影片仍會 15 分鐘自動刪除，所以你電腦不會被別人塞滿。

**電腦容量會用多少？**
- 常駐：約 **1.3 GB**（Whisper model + 已包含 ffmpeg 的 .app 本體）
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
| 瀏覽器有開但網頁打不開 | port 5057 被佔了，重開機或關掉其他程式 |
| 「無法打開，開發者未驗證」 | 右鍵 App → 打開（一次性允許） |
| 上傳跳「影片格式無法讀取」 | 重新匯出成 `.mp4`，大部分剪輯軟體預設都是這個 |
| Intel Mac 轉錄超慢 | 對，Apple Silicon 跑 Whisper 快 3–5 倍。有 M 系列就用 M 系列 |
| 第一次啟動下載了 400 MB | 正常，那是 Whisper model，下載一次就好 |
| 開不起來，說檔案缺失 | App 包裝壞了，從 [Releases](../../releases/latest) 重新下載一份就好（ffmpeg + ffprobe 已經包在裡面，不用另外裝） |

---

## Last Update

2026.05

## License

[MIT](LICENSE) — do whatever you want, but I'm not responsible for what you do with it.

## Credits

Built by **Jessie D. Chang** ([LinkedIn](https://www.linkedin.com/in/taofang-chang)) with the help of Claude.

Speech recognition: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
Traditional Chinese conversion: [OpenCC](https://github.com/yichen0831/opencc-python)
