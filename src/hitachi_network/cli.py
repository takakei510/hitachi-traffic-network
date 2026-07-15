from __future__ import annotations

import argparse
from pathlib import Path

from .io import load_road_graph
from .simulation import run_comparison, write_comparison_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a cascade-failure comparison on the Hitachi road network.")
    parser.add_argument("--nodes", type=Path, default=Path("data/raw/Hitachinodes.csv"), help="Path to the node CSV file.")
    parser.add_argument("--edges", type=Path, default=Path("data/raw/Hitachiedges.csv"), help="Path to the edge CSV file.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/cascade"), help="Directory for CSV, JSON, and PNG outputs.")
    parser.add_argument("--attack-count", type=int, default=10, help="Number of nodes to attack in each scenario.")
    parser.add_argument("--random-trials", type=int, default=10, help="Number of random-failure trials to run.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling and load approximation.")
    parser.add_argument("--load-model", choices=["betweenness", "degree"], default="betweenness", help="Node-load model used for cascade simulation.")
    parser.add_argument("--sample-size", type=int, default=64, help="Sample size for approximate betweenness centrality.")
    parser.add_argument("--alpha", "--tolerance", dest="alpha", type=float, default=0.2, help="Capacity tolerance relative to initial load.")
    parser.add_argument("--plot-metric", choices=["remaining_nodes", "largest_component_size"], default="remaining_nodes", help="Metric to show in the comparison plot.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    graph = load_road_graph(args.nodes, args.edges, mode="directed")
    results = run_comparison(
        graph,
        attack_count=args.attack_count,
        random_trials=args.random_trials,
        seed=args.seed,
        load_model=args.load_model,
        sample_size=args.sample_size,
        alpha=args.alpha,
    )
    outputs = write_comparison_outputs(results, args.output_dir, plot_metric=args.plot_metric)

    print(f"loaded nodes: {graph.number_of_nodes():,}")
    print(f"loaded edges: {graph.number_of_edges():,}")
    random_summary = results.random_summary
    high_load_summary = results.high_load_summary
    print(
        "random_failure: "
        f"trials={random_summary['trial_count']:,}, "
        f"final_surviving_nodes={random_summary['final_surviving_nodes_mean']:.2f} ± {random_summary['final_surviving_nodes_std']:.2f}, "
        f"largest_component_size={random_summary['final_largest_component_size_mean']:.2f} ± {random_summary['final_largest_component_size_std']:.2f}, "
        f"cascade_steps={random_summary['cascade_steps_mean']:.2f} ± {random_summary['cascade_steps_std']:.2f}"
    )
    print(
        "high_load_failure: "
        f"final_surviving_nodes={high_load_summary['final_surviving_nodes_mean']:.2f}, "
        f"largest_component_size={high_load_summary['final_largest_component_size_mean']:.2f}, "
        f"cascade_steps={high_load_summary['cascade_steps_mean']:.2f}"
    )
    print(f"saved summary CSV: {outputs['summary_csv']}")
    print(f"saved trials CSV: {outputs['trials_csv']}")
    print(f"saved steps CSV: {outputs['steps_csv']}")
    print(f"saved JSON: {outputs['json']}")
    print(f"saved PNG: {outputs['png']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
