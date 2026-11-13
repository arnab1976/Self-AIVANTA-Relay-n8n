"""Write the built-in AIVANTA templates as importable n8n workflow files (n8n/workflows/*.json).

    python scripts/export_n8n_workflows.py [--mode native|service]

The files are what AIVANTA deploys through the n8n API at publish/run time,
with placeholder credential ids. They are useful for review, diffing and a
manual import (n8n → Workflows → Import from file).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aivanta_graph import TEMPLATES, template_graph
from aivanta_runtime.n8n_compiler import CompileOptions, compile_workflow


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="native", choices=["native", "service"])
    ap.add_argument("--out", default="n8n/workflows")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for key, (name, _desc, _fn) in TEMPLATES.items():
        if key == "BLANK":
            continue
        g = template_graph(key)
        wf = compile_workflow(g, CompileOptions(agent_mode=a.mode, workflow_name=f"AIVANTA · template · {name}",
                                                webhook_path=f"aivanta/template/{key.lower()}", bridge_url="http://api:8000"))
        wf.pop("meta", None)
        path = out / f"{key.lower()}.{a.mode}.json"
        path.write_text(json.dumps(wf, indent=2, ensure_ascii=False))
        print(f"{path}  ({len(wf['nodes'])} n8n nodes from {len(g.nodes)} canvas nodes)")


if __name__ == "__main__":
    main()
