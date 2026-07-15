from __future__ import annotations

import argparse
import re
from pathlib import Path

from .io import load_road_graph
from .simulation import run_comparison, write_comparison_outputs
from .sensitivity import run_sensitivity_analysis, write_sensitivity_outputs


def _parse_csv_floats(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _parse_csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


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
    parser.add_argument("--sensitivity-output-dir", type=Path, default=None, help="Directory for sensitivity-analysis outputs.")
    parser.add_argument("--sensitivity-alpha-values", type=str, default="0.1,0.2,0.5,1.0", help="Comma-separated alpha values for sensitivity analysis.")
    parser.add_argument("--sensitivity-sample-sizes", type=str, default="8,32,100", help="Comma-separated sample sizes for sensitivity analysis.")
    parser.add_argument("--sensitivity-random-trials", type=int, default=10, help="Random trials per condition for sensitivity analysis.")
    parser.add_argument("--sensitivity-attack-count", type=int, default=2, help="Attack count for sensitivity analysis.")
    parser.add_argument("--sensitivity-load-model", choices=["betweenness", "degree"], default="betweenness", help="Load model for sensitivity analysis.")
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

    if args.sensitivity_output_dir is not None:
        alpha_values = _parse_csv_floats(args.sensitivity_alpha_values)
        sample_sizes = _parse_csv_ints(args.sensitivity_sample_sizes)
        print("[sensitivity] starting")
        sensitivity_result = run_sensitivity_analysis(
            graph,
            alphas=alpha_values,
            sample_sizes=sample_sizes,
            attack_count=args.sensitivity_attack_count,
            random_trials=args.sensitivity_random_trials,
            seed=args.seed,
            load_model=args.sensitivity_load_model,
            progress=print,
        )
        sensitivity_outputs = write_sensitivity_outputs(sensitivity_result, args.sensitivity_output_dir)
        print(f"saved sensitivity CSV: {sensitivity_outputs['trial_csv']}")
        print(f"saved sensitivity summary CSV: {sensitivity_outputs['summary_csv']}")
        print(f"saved sensitivity JSON: {sensitivity_outputs['json']}")
        print(f"saved alpha PNG: {sensitivity_outputs['alpha_png']}")
        print(f"saved sample-size PNG: {sensitivity_outputs['sample_size_png']}")
        print(f"saved zero-load PNG: {sensitivity_outputs['zero_load_png']}")
        print(f"saved comparison PNG: {sensitivity_outputs['comparison_png']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
