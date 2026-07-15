# Hitachi Traffic Network

日立周辺の道路ネットワークを用いて、媒介中心性・輻輳・カスケード故障を共同分析するためのPythonプロジェクトです。

## 現在できること

- ノードCSV・エッジCSVの読み込み
- NetworkX `MultiDiGraph` / `MultiGraph` の生成
- 道路網の画像出力
- 任意の負荷計算を差し込めるカスケード故障処理の雛形

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
```

成功すると `outputs/hitachi_network.png` が生成されます。

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
