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
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling and load approximation.")
    parser.add_argument("--load-model", choices=["betweenness", "degree"], default="betweenness", help="Node-load model used for cascade simulation.")
    parser.add_argument("--sample-size", type=int, default=64, help="Sample size for approximate betweenness centrality.")
    parser.add_argument("--tolerance", type=float, default=0.2, help="Capacity tolerance relative to initial load.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    graph = load_road_graph(args.nodes, args.edges, mode="directed")
    results = run_comparison(
        graph,
        attack_count=args.attack_count,
        seed=args.seed,
        load_model=args.load_model,
        sample_size=args.sample_size,
        tolerance=args.tolerance,
    )
    outputs = write_comparison_outputs(results, args.output_dir)

    print(f"loaded nodes: {graph.number_of_nodes():,}")
    print(f"loaded edges: {graph.number_of_edges():,}")
    for result in results:
        print(
            f"{result.name}: attacked={len(result.attack_nodes):,}, failed={result.summary['failed_count']:,}, "
            f"surviving={result.summary['surviving_nodes']:,}, steps={result.summary['cascade_steps']:,}"
        )
    print(f"saved summary CSV: {outputs['summary_csv']}")
    print(f"saved steps CSV: {outputs['steps_csv']}")
    print(f"saved JSON: {outputs['json']}")
    print(f"saved PNG: {outputs['png']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
