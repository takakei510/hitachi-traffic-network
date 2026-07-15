# Design

## 目的

日立周辺の道路ネットワークを使って、ノード障害が連鎖的に波及する様子を再現し、比較可能な形式で出力する。

## 実装方針

- 入力は `data/raw/Hitachinodes.csv` と `data/raw/Hitachiedges.csv` を前提にする。
- 読み込みは `src/hitachi_network/io.py` が担当する。
- 可視化は `src/hitachi_network/plotting.py` が担当する。
- カスケード制御は `src/hitachi_network/cascade.py` が担当し、負荷の計算は外部から差し込む。
- 交通網向けの分析ロジックは `src/hitachi_network/simulation.py` にまとめる。

## 現在のデータモデル

- ノードは `osmid` を識別子として扱う。
- エッジは `u`, `v`, `key`, `length` を中心に扱う。
- 多重辺は解析前に単純化し、同一端点間では最短の `length` を持つ辺を採用する。

## カスケード計算

- 初期負荷はノード負荷モデルで計算する。
- 負荷モデルは現在 `betweenness` と `degree` を用意している。
- 容量は `initial_load * (1 + tolerance)` とする。
- 初期攻撃ノードを除去したあと、各ステップで再計算した負荷が容量を超えたノードを同時に削除する。
- 収束するまで繰り返し、ステップごとの失敗履歴を保持する。

## 比較シナリオ

- ランダム故障: ノード集合から乱択で選ぶ。
- 高負荷ノード故障: 初期負荷が高い順に選ぶ。
- 両シナリオは同じグラフ、同じ負荷モデル、同じ容量条件で比較する。

## 出力

- CSV: 要約とステップ推移を分けて保存する。
- JSON: シナリオ全体の構造化結果を保存する。
- PNG: シナリオ間の残存ノード数の比較図を保存する。

## 実行方法

- `python -m hitachi_network`
- 主要オプション:
  - `--attack-count`
  - `--seed`
  - `--load-model`
  - `--sample-size`
  - `--tolerance`
  - `--output-dir`
