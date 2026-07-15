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

## 2026-07-15 Streamlit UI 追加

- 変更内容: `src/hitachi_network/streamlit_app.py` と `app.py` を追加し、Plotly ベースの地図クリック選択、候補ノード選択、ランダム故障、高負荷ノード故障を切り替えられる展示用 UI を実装した。
- 変更理由: 来場者が故障地点を直感的に選び、既存のカスケード故障モデルの結果をその場で確認できるようにするため。
- 実装方針:
  - シミュレーション本体は変更せず、UI は変換関数と表示だけを担当する。
  - 読み込みはキャッシュし、描画は Plotly `Scattergl` を使って重さを抑える。
  - 初期故障ノードの分類、表示用 DataFrame、指標計算は純粋関数として分離した。
- 動作確認結果:
  - `python -m pytest` は成功した。
  - `streamlit run app.py --server.headless true --server.port 8501` は起動し、Streamlit サーバーの待受を確認した。
- 残課題:
  - ノード数が多い環境では、ブラウザ性能によっては表示が重くなる可能性がある。
  - クリック選択は実装したが、展示環境によっては候補ノード選択の方が安定する場合がある。

## 2026-07-15 地点検索と半径指定の追加

- 変更内容: Nominatim を使った場所名検索、半径指定、部分グラフ抽出、OpenStreetMap 背景の地図表示、Google Maps リンク生成を追加し、`streamlit_app.py` を再構成した。
- 変更理由: 来場者が「日立駅」「茨城大学日立キャンパス」などを入力して、その周辺だけを見ながら故障シミュレーションを試せるようにするため。
- 実装方針:
  - Nominatim からの検索結果変換、距離計算、半径抽出、Maps URL 生成は `src/hitachi_network/geospatial.py` に切り出した。
  - 検索は `st.cache_data` でキャッシュし、補助語として `茨城県 日立市` を追加する。
  - シミュレーションは既定で部分グラフ上で実行し、必要なら全体グラフに切り替えられるようにした。
  - 既存のカスケード計算ロジックは変更していない。
- 動作確認結果:
  - `python -m pytest` は 23 passed。
  - `streamlit run app.py --server.headless true --server.port 8501` は起動し、待受開始を確認した。
- 残課題:
  - Nominatim は外部サービスなので、ネットワーク環境に依存する。
  - 表示範囲が広い場合は、ブラウザ側の描画負荷が高くなる可能性がある。

## 2026-07-15 結果表示の性能切り分け

- 変更内容: Streamlit の結果表示を Plotly のインタラクティブ地図から、Matplotlib の静的 PNG に切り替えた。結果表は故障ノードのみを最大 200 件に制限し、`session_state` は選択ノード ID、パラメータ、`failed_by_step`、数値指標、結果画像の軽量データだけを保持するように整理した。
- 変更理由: カスケード計算は短時間で終わっている一方で、結果地図と結果表の描画が灰色のローディング表示のまま完了しない現象を、フロントエンド描画と再実行ループの観点で切り分けるため。
- 実装方針:
  - 選択用地図だけに `plotly_events` を残し、結果表示では呼ばない。
  - 結果地図は Matplotlib で PNG 化し、背景エッジは最大 3000 本、正常ノードは原則描画しない。
  - 結果表示用の数値は `st.metric` を使わず、単純な `st.write` / `st.markdown` 表示に寄せた。
  - `st.cache_data` は軽量なタプルや PNG 用データに限定し、Graph や Plotly Figure、巨大 DataFrame は保存しない。
  - Matplotlib は `Agg` バックエンドに固定して、表示環境差で止まらないようにした。
- 動作確認結果:
  - `python -m pytest` は成功した。
  - `streamlit run app.py --server.headless true --server.port 8501` は起動し、待受開始を確認した。
- 補足:
  - Playwright による自動確認は待機状態になったため中止し、最終確認は手動で行う方針に切り替えた。

