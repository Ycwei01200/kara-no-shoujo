# shell-guide

galgame《殼之少女 The Shell Part I》的攻略桌寵。
平常是螢幕角落的一個小頭像。偵測到**對話選項、地圖、推理清單**畫面時，會彈出泡泡告訴你該選哪個。

## 使用
1. 第一次使用：`pip install -r requirements.txt`，再執行 `python -X utf8 tools/build_all.py`（約 5 分鐘）
2. 雙擊 `start-pet.bat`
3. 右鍵頭像 → 「目標結局」，選你要攻的結局

- 拖曳頭像可以移動位置。滑鼠移到頭像上，會顯示目前進度。
- 外圈變橘色：目前場景不在目標路線上，代表前面選錯了。請讀取較早的存檔。
- 右鍵 →「完整路線…」：列出整條路線。點其中一步，等於告訴它「我現在在這」。
- 外圈變灰色：已暫停，或找不到遊戲視窗／OCR 出錯。滑鼠移到頭像上看原因。
- 遊戲語言要設成**繁體中文**。遊戲要用**視窗模式或無邊框全螢幕**，不能最小化（獨佔全螢幕時截不到畫面，桌寵也會被蓋住）。
- 頭像不要放在遊戲的選項或對話框上方：頭像周圍 380×300 的範圍不會被 OCR 讀取。
- 推理答錯時，桌寵會自動退回同一題，再提示一次。

## 運作方式
- `tools/build_all.py`：從遊戲封包（Artemis pf8/pf6）解出腳本，用 BFS 模擬所有分歧，再把每個結局的路線逐步重播驗證，產生 `data/routes.json`。
- `guide/core.py`：資料比對、OCR 執行緒、路線追蹤，桌寵和大視窗共用。
- `guide/pet.py`：每秒截一次遊戲畫面，用 Windows 內建繁中 OCR 辨識，再和腳本台詞、選項比對來定位進度。
- 測試（不需要開遊戲）：`python -X utf8 guide/test_match.py`、`guide/test_tracker.py`。
- `guide/app.py`：詳細模式的大視窗，可以不用。

## 需求
- Windows 10/11，並安裝「中文（繁體，台灣）」語言的 OCR 元件
- Python 3.12

## 資料與版權
`data/` 是從你自己安裝的遊戲解出的內容，不納入版控，也不要散布。
遊戲預設路徑是 `D:\Steam\steamapps\common\The Shell Part I`。路徑不同的話，請把它當作第一個參數傳給 `build_all.py`。
