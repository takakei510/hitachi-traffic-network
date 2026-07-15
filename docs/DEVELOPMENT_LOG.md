# Development Log

## 2026-07-15

- `docs/DESIGN.md` と `docs/COPILOT_TASK.md` はワークスペース内に存在しなかったため、既存コードとユーザー指定の優先順位を基準に実装方針を決めた。
- カスケード故障の高レベル実装を追加した。
- `src/hitachi_network/simulation.py` に、道路ネットワークの単純化、負荷計算、ランダム故障と高負荷ノード故障の比較、CSV/JSON/PNG 出力を実装した。
- `src/hitachi_network/cli.py` と `src/hitachi_network/__main__.py` を追加し、`python -m hitachi_network` で実行できる CLI を用意した。
- `src/hitachi_network/plotting.py` に比較用 PNG の作図を追加した。
- `pyproject.toml` を追加し、editable install で CLI を使えるようにした。
- `tests/test_cascade.py` を追加し、マルチエッジ縮約、負荷順の選択、比較実行の基本動作を検証した。
- 検証結果:
  - `python -m pytest tests/test_cascade.py tests/test_io.py` が成功した。
  - `python -m hitachi_network --attack-count 2 --sample-size 8 --load-model betweenness --output-dir outputs/cascade_test` を実行し、`cascade_summary.csv`、`cascade_steps.csv`、`cascade_results.json`、`cascade_comparison.png` を生成した。

## 2026-07-15 追記

- 変更内容: 交通網カスケード故障の本体、CLI、結果保存、比較プロット、テスト、配布用メタデータを追加した。
- 変更理由: 優先順位の高い要件である「カスケード計算」「コマンドライン実行」「CSV/JSON/PNG 保存」「ランダム故障と高負荷ノード故障の比較」を先に成立させるため。
- 動作確認結果:
  - `python -m pytest tests/test_cascade.py tests/test_io.py` は成功。
  - `python -m hitachi_network --attack-count 2 --sample-size 8 --load-model betweenness --output-dir outputs/cascade_test` は成功し、`outputs/cascade_test/` に `cascade_summary.csv`、`cascade_steps.csv`、`cascade_results.json`、`cascade_comparison.png` を出力。
- 残課題:
  - GUI とアニメーションは未実装。
  - `docs/DESIGN.md` と `docs/COPILOT_TASK.md` は元からワークスペースに存在しないため、元設計との差分レビューは未実施。
  - 交通シナリオや容量モデルの調整、表示指標の追加は今後の拡張候補。

## 2026-07-15 再検証

- 変更内容: random_failure の複数試行集計、ステップごとの `remaining_nodes` / `largest_component_size` / `newly_failed_count` / `cumulative_failed_count` / `newly_failed_nodes` / `max_load_ratio` 記録、自己ループ除去、展示向けプロット切替を追加した。
- 変更理由: 比較条件を揃え、出力の不整合を解消し、random_failure の平均と標準偏差を明示できるようにするため。
- 動作確認結果:
  - `python -m pytest` が成功した。
  - `python -m hitachi_network --attack-count 2 --sample-size 8 --load-model betweenness --seed 42 --random-trials 10 --output-dir outputs/cascade_verified` が成功し、`outputs/cascade_verified/` に `cascade_summary.csv`、`cascade_trials.csv`、`cascade_steps.csv`、`cascade_results.json`、`cascade_comparison.png` を出力。
  - 実測値は `random_failure` 平均 `final_surviving_nodes=6366.60 ± 498.51`、`largest_component_size=862.20 ± 222.06`、`cascade_steps=14.70 ± 6.58`、`high_load_failure` は `final_surviving_nodes=7149.00`、`largest_component_size=1640.00`、`cascade_steps=22.00` だった。
- 残課題:
  - GUI とアニメーションは未実装。
  - 乱数試行の集計やプロットは実装したが、展示用の説明文は今後さらに短く整える余地がある。

