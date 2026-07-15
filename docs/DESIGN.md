# Design

## 目的

日立周辺の道路ネットワークを使って、ノード障害が連鎖的に波及する様子を再現し、比較可能な形式で出力する。

## 実装方針

- 入力は `data/raw/Hitachinodes.csv` と `data/raw/Hitachiedges.csv` を前提にする。
- 読み込みは `src/hitachi_network/io.py` が担当する。
- 可視化は `src/hitachi_network/plotting.py` が担当する。
- カスケード制御は `src/hitachi_network/cascade.py` が担当し、負荷の計算は外部から差し込む。
- 交通網向けの分析ロジック、複数試行の集計、出力整形は `src/hitachi_network/simulation.py` にまとめる。
- 展示用 UI は `src/hitachi_network/streamlit_app.py` が担当し、既存のシミュレーション関数を呼び出すだけにする。
- 地点検索、半径抽出、Google Maps リンク生成は `src/hitachi_network/geospatial.py` に切り出す。

## 現在のデータモデル

- ノードは `osmid` を識別子として扱う。
- エッジは `u`, `v`, `key`, `length` を中心に扱う。
- 多重辺は解析前に単純化し、同一端点間では最短の `length` を持つ辺を採用する。
- 自己ループは解析から除外する。

## カスケード計算

- 初期負荷はノード負荷モデルで計算する。
- 負荷モデルは現在 `betweenness` と `degree` を用意している。
- 容量は `C_i = (1 + alpha) * L_i(0)` とする。
- 初期攻撃ノードを除去したあと、各ステップで再計算した負荷が容量を超えたノードを同時に削除する。
- 収束するまで繰り返し、ステップごとの失敗履歴を保持する。
- 各ステップは `remaining_nodes` と `largest_component_size` を両方記録する。

## 比較シナリオ

- ランダム故障: ノード集合から乱択で選ぶ。複数回試行し、平均と標準偏差を集計する。
- 高負荷ノード故障: 初期負荷が高い順に選ぶ。1 回だけ実行する。
- 両シナリオは同じグラフ、同じ負荷モデル、同じ `alpha`、同じ `attack_count`、同じ `sample_size`、同じ `seed` を使う。
- ランダム故障の乱数は試行番号ごとに再現可能な形で分ける。

## 出力

- CSV: 要約、試行別結果、ステップ推移を分けて保存する。
- JSON: パラメータ、要約、試行別結果、ステップ推移を保存する。
- PNG: `remaining_nodes` または `largest_component_size` の比較図を保存する。
- 出力には `alpha`、`attack_count`、`sample_size`、`seed`、`load_model` を含める。

## Streamlit UI

- UI はシミュレーション本体と分離する。
- 場所検索は OpenStreetMap Nominatim を使い、検索語に茨城県日立市を補助的に付ける。
- 検索結果は `st.cache_data` でキャッシュし、連続リクエストを避ける。
- 半径は `500 m`、`1 km`、`2 km`、`3 km` を選べるようにする。
- 部分グラフは検索中心からの半径内ノードのみを含み、外側のノードは描画しない。
- 既定の実行範囲は部分グラフとし、全体グラフへの切り替えもできるようにする。
- 描画は Plotly `Scattermapbox` を使い、OpenStreetMap の背景を表示する。
- 検索地点は専用マーカーと円で示し、ノードは緯度・経度と近隣名称をホバー表示する。
- UI の色分けは正常ノード灰色、初期故障黒、連鎖故障赤、最大連結成分青系とする。

## 実行方法

- `python -m hitachi_network`
- `streamlit run app.py`
- 主要オプション:
  - `--attack-count`
  - `--random-trials`
  - `--seed`
  - `--load-model`
  - `--sample-size`
  - `--alpha`
  - `--plot-metric`
  - `--output-dir`

## 2026-07-15 検証結果

- `python -m pytest` は成功した。
- `python -m hitachi_network --attack-count 2 --sample-size 8 --load-model betweenness --seed 42 --random-trials 10 --output-dir outputs/cascade_verified` を実行し、CSV、JSON、PNG を生成した。
- このデータでは `random_failure` の平均値が `high_load_failure` より小さく、最終残存ノード数と最大連結成分サイズの両方で被害が大きく見えた。実装上の条件差ではなく、現データでの結果としてそのまま扱う。
- `streamlit run app.py --server.headless true --server.port 8501` が起動し、Streamlit サーバーの待受開始を確認した。
- `python -m pytest` は再度成功し、地理検索、半径抽出、Google Maps URL 生成、Streamlit UI 補助関数のテストも通過した。
