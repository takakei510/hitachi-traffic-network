# Hitachi Traffic Network

日立周辺の道路ネットワークを用いて、媒介中心性・輻輳・カスケード故障を共同分析するためのPythonプロジェクトです。

## 現在できること

- ノードCSV・エッジCSVの読み込み
- NetworkX `MultiDiGraph` / `MultiGraph` の生成
- 道路網の画像出力
- 任意の負荷計算を差し込めるカスケード故障処理の雛形
- Streamlit による展示向けの操作画面

## Streamlit 操作画面

次のいずれかで起動できます。

```powershell
streamlit run app.py
```

```powershell
streamlit run src/hitachi_network/streamlit_app.py
```

操作の流れ:

1. まず場所名を入力して `場所を探す` を押します。初期値は `日立駅` です。
2. 候補が複数ある場合は、候補一覧から表示したい地点を選びます。
3. `500 m`、`1 km`、`2 km`、`3 km` から範囲を選びます。
4. `部分グラフ` か `全体グラフ` かを選び、初期状態は部分グラフで実行します。
5. `地図クリック`、`候補ノード選択`、`ランダム故障`、`高負荷ノード故障` から故障地点を選びます。
6. `シミュレーションを実行` を押すと、カスケード故障の結果が表示されます。
7. `各 cascade_step を表示` を有効にすると、段階ごとの状態を切り替えられます。

表示される主な指標:

- 初期ノード数
- 最終残存ノード数
- 累積故障ノード数
- 最大連結成分サイズ
- 最大連結成分比
- カスケードステップ数

色分け:

- 灰色: 正常ノード
- 黒: 初期故障ノード
- 赤: 連鎖故障ノード
- 青系: 最大連結成分に残るノード

検索地点には Google Maps のリンクを表示します。API キーは不要で、緯度・経度だけで開ける URL 形式を使います。

この UI は、実際の交通流を厳密に再現したものではなく、複雑ネットワーク理論に基づく簡易カスケード故障モデルの可視化です。

## 環境構築（Windows PowerShell）

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 最初の動作確認

```powershell
python examples/01_load_and_plot.py
pytest
streamlit run app.py
```

成功すると `outputs/hitachi_network.png` が生成されます。

Streamlit 画面はブラウザで開き、場所検索、半径指定、地図上のノード選択とカスケード結果の確認ができます。

## ディレクトリ構成

```text
data/raw/                 元CSV
src/hitachi_network/io.py 読み込み
src/hitachi_network/plotting.py 可視化
src/hitachi_network/cascade.py カスケード故障
examples/                  実行例
outputs/                   生成物（Git管理外）
tests/                     テスト
```

## 共同開発で先に決めること

1. グラフを有向として扱うか、無向として扱うか
2. 負荷をノードに置くか、道路（エッジ）に置くか
3. 初期負荷の定義（媒介中心性、OD交通量、ランダム需要など）
4. 容量 `C_i = (1 + alpha) L_i(0)` の `alpha`
5. 故障後の負荷再計算方法
6. 評価指標（最大連結成分、到達可能率、故障数など）

## GitHub開始例

```powershell
git init
git add .
git commit -m "Initial project setup"
git branch -M main
git remote add origin <GitHub repository URL>
git push -u origin main
```

CSVを公開リポジトリに置いてよいか不明な場合は、`data/raw/*.csv` を `.gitignore` に追加してください。
