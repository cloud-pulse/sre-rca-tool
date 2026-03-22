import sys
import os
try:
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

import re
import yaml
from pathlib import Path
from core.logger import get_logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich import box

log = get_logger("service_graph")
console = Console()

SERVICES_FILE = "services.yaml"

class ServiceGraph:
    def __init__(self, services_file: str = SERVICES_FILE):
        self.services_file = services_file
        self.services = {}
        self._load()

    def _load(self):
        try:
            with open(self.services_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if data and 'services' in data:
                    self.services = data['services']
                else:
                    self.services = {}
            if self.services:
                pass
        except FileNotFoundError:
            log.warn("services.yaml not found")
            self.services = {}
        except Exception as e:
            log.error(f"Invalid services.yaml: {e}")
            self.services = {}

    def _save(self):
        try:
            with open(self.services_file, 'w', encoding='utf-8') as f:
                yaml.dump(
                    {"services": self.services},
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True
                )
        except Exception as e:
            log.error(f"Save failed: {e}")

    def get_all_service_names(self) -> list[str]:
        return list(self.services.keys())

    def get_service(self, name: str) -> dict | None:
        if name in self.services:
            return self.services[name]
        for key, value in self.services.items():
            if name in key or key in name:
                return value
        return None

    def get_service_name(self, name: str) -> str | None:
        if name in self.services:
            return name
        for key in self.services.keys():
            if name in key or key in name:
                return key
        return None

    def get_containers(self, service_name: str) -> list[str]:
        svc = self.services.get(service_name, {})
        containers = svc.get("containers", [])
        result = []
        for c in containers:
            if isinstance(c, dict):
                result.append(c.get("name", str(c)))
            else:
                result.append(str(c))
        return result

    def get_namespace(self, service_name: str, default: str = "default") -> str:
        svc = self.services.get(service_name, {})
        return svc.get("namespace", default)

    def get_downstream(self, service: str, depth: int = 5, _visited: set = None) -> list[str]:
        if _visited is None:
            _visited = set()
        if depth == 0 or service in _visited:
            return []
            
        _visited.add(service)
        svc = self.get_service(service)
        if not svc:
            return []
            
        downstream = set(svc.get("depends_on", []) or [])
        res = set(downstream)
        for d in downstream:
            res.update(self.get_downstream(d, depth - 1, _visited.copy()))
        return list(res)

    def get_upstream(self, service: str, depth: int = 5, _visited: set = None) -> list[str]:
        if _visited is None:
            _visited = set()
        if depth == 0 or service in _visited:
            return []
            
        _visited.add(service)
        svc = self.get_service(service)
        if not svc:
            return []
            
        upstream = set(svc.get("exposes_to", []) or [])
        for k, v in self.services.items():
            if service in (v.get("depends_on", []) or []):
                upstream.add(k)
                
        res = set(upstream)
        for u in upstream:
            res.update(self.get_upstream(u, depth - 1, _visited.copy()))
        return list(res)

    def get_blast_radius(self, service: str) -> dict:
        canon = self.get_service_name(service) or service
        ds = self.get_downstream(canon)
        us = self.get_upstream(canon)
        all_affected = set([canon] + ds + us)
        safe = [s for s in self.get_all_service_names() if s not in all_affected]
        return {
            "target": canon,
            "downstream": ds,
            "upstream": us,
            "all_affected": list(all_affected),
            "safe_services": safe,
            "total_services": len(self.services)
        }

    def discover_from_logs(self, log_lines: list[str], source_service: str) -> list[dict]:
        source_canon = self.get_service_name(source_service) or source_service
        
        high = [
            r"connecting to ([a-zA-Z0-9_-]+)",
            r"calling ([a-zA-Z0-9_-]+)",
            r"upstream:\s*([a-zA-Z0-9_-]+)",
            r"forwarding to ([a-zA-Z0-9_-]+)",
            r"host:\s*([a-zA-Z0-9_-]+)",
            r"grpc://([a-zA-Z0-9_-]+)",
            r"http://([a-zA-Z0-9_-]+)",
            r"([a-zA-Z0-9_-]+):\d+"
        ]
        
        medium = [
            r"connection refused from ([a-zA-Z0-9_-]+)",
            r"failed to reach ([a-zA-Z0-9_-]+)",
            r"timeout.*([a-zA-Z0-9_-]+)",
            r"waiting for ([a-zA-Z0-9_-]+)",
            r"unable to connect.*([a-zA-Z0-9_-]+)"
        ]
        
        skip = {"the", "to", "from", "and", "for", "with", "http", "https", "tcp", "localhost", "127.0.0.1", "0.0.0.0"}
        
        svc_config = self.get_service(source_canon) or {}
        existing_deps = set(svc_config.get("depends_on", []) or [])
        
        results = {}
        
        def process(m, conf, line):
            tgt = m.group(1).lower()
            tgt = tgt.split(":")[0]
            if len(tgt) < 3 or tgt in skip:
                return
            if tgt == source_canon or tgt in existing_deps:
                return
            
            if tgt not in results or conf == "high":
                already = self.get_service_name(tgt) is not None
                results[tgt] = {
                    "target": tgt,
                    "source": source_canon,
                    "confidence": conf,
                    "evidence": line[:100],
                    "already_in_graph": already
                }
                
        for line in log_lines:
            matched = False
            for p in high:
                m = re.search(p, line, re.IGNORECASE)
                if m:
                    process(m, "high", line)
                    matched = True
            if not matched:
                for p in medium:
                    m = re.search(p, line, re.IGNORECASE)
                    if m:
                        process(m, "medium", line)
                        
        return list(results.values())

    def prompt_user_to_update(self, discoveries: list[dict], source_service: str) -> bool:
        if not discoveries:
            return False
            
        console.print(f"Found {len(discoveries)} new dependencies for {source_service}")
        
        table = Table()
        table.add_column("Target Service")
        table.add_column("Confidence")
        table.add_column("Evidence")
        table.add_column("Status")
        
        for d in discoveries:
            status = "new dep" if d["already_in_graph"] else "new service"
            table.add_row(d["target"], d["confidence"], d["evidence"], status)
            
        console.print(table)
        
        try:
            ans = console.input("Update services.yaml? (y/n): ").strip().lower()
            return ans in ("y", "yes")
        except KeyboardInterrupt:
            print()
            return False

    def apply_discoveries(self, discoveries: list[dict], source_service: str):
        source_canon = self.get_service_name(source_service) or source_service
        
        for d in discoveries:
            tgt = d["target"]
            if d["already_in_graph"]:
                tgt_canon = self.get_service_name(tgt)
                if tgt_canon:
                    if source_canon in self.services:
                        deps = self.services[source_canon].get("depends_on", [])
                        if deps is None: deps = []
                        if tgt_canon not in deps:
                            deps.append(tgt_canon)
                            self.services[source_canon]["depends_on"] = deps
                            console.print(f"[+] {source_canon} now depends_on {tgt_canon}")
            else:
                self.services[tgt] = {
                    "description": f"Auto-discovered dependency",
                    "namespace": self.get_namespace(source_canon),
                    "depends_on": [],
                    "exposes_to": [source_canon],
                    "containers": [{"name": tgt}],
                    "dependency_confidence": f"discovered_{d['confidence']}",
                    "auto_discovered": True
                }
                if source_canon in self.services:
                    deps = self.services[source_canon].get("depends_on", [])
                    if deps is None: deps = []
                    if tgt not in deps:
                        deps.append(tgt)
                        self.services[source_canon]["depends_on"] = deps
                console.print(f"[+] {source_canon} now depends_on {tgt}")
                console.print(f"[+] New service added: {tgt}")
                
        self._save()

    def print_graph(self):
        table = Table(title="Service Dependencies")
        table.add_column("Service")
        table.add_column("Namespace")
        table.add_column("Depends On")
        table.add_column("Exposes To")
        table.add_column("Confidence")
        table.add_column("Containers")
        
        for name, cfg in self.services.items():
            deps = cfg.get("depends_on", []) or []
            exps = cfg.get("exposes_to", []) or []
            conf = cfg.get("dependency_confidence", "user_defined")
            containers = self.get_containers(name)
            
            table.add_row(
                name,
                cfg.get("namespace", "default"),
                ", ".join(deps) if deps else "none",
                ", ".join(exps) if exps else "none",
                str(conf),
                ", ".join(containers) if containers else "none"
            )
            
        console.print(table)

    def print_blast_radius(self, service: str):
        br = self.get_blast_radius(service)
        
        ds = ["    → " + d for d in br["downstream"]]
        us = ["    → " + u for u in br["upstream"]]
        sf = ["    ✓ " + s for s in br["safe_services"]]
        
        content = "  Downstream (calls):\n"
        content += "\n".join(ds) if ds else "    (none)"
        content += "\n  Upstream (called by):\n"
        content += "\n".join(us) if us else "    (none)"
        content += "\n  Safe (not affected):\n"
        content += "\n".join(sf) if sf else "    (none)"
        
        panel = Panel(content, title=f"Blast Radius: [bold red]{br['target']}[/bold red]")
        console.print(panel)

if __name__ == "__main__":
    print(
        "=== Task F — Service Graph Test ===\n"
    )

    graph = ServiceGraph()
    all_services = graph.get_all_service_names()
    print(f"Services loaded: {all_services}\n")

    print("--- Test 1: Print full graph ---")
    graph.print_graph()

    print("--- Test 2: Blast radius for "
          "each service ---")
    for svc in all_services:
        br = graph.get_blast_radius(svc)
        print(f"\n  {svc}:")
        print(
            f"    downstream: "
            f"{br['downstream']}"
        )
        print(
            f"    upstream  : "
            f"{br['upstream']}"
        )
        print(
            f"    safe      : "
            f"{br['safe_services']}"
        )

    print("\n--- Test 3: Blast radius panel ---")
    if all_services:
        graph.print_blast_radius(
            all_services[0]
        )

    print("--- Test 4: Container lookup ---")
    for svc in all_services:
        containers = graph.get_containers(svc)
        print(
            f"  {svc}: {containers}"
        )

    print("\n--- Test 5: Partial name match ---")
    for svc in all_services:
        partial = svc.split("-")[0]
        resolved = graph.get_service_name(
            partial
        )
        print(
            f"  '{partial}' → '{resolved}'"
        )

    print(
        "\n--- Test 6: Discovery from logs ---"
    )
    mock_service = (
        all_services[0]
        if all_services else "my-service"
    )
    mock_logs = [
        f"connecting to new-cache-service:6379",
        f"upstream: unknown-gateway timeout",
        f"connection refused from "
        f"{all_services[-1] if all_services else 'db'}",
        f"forwarding to totally-new-service",
        f"host: another-service:8080",
    ]
    discoveries = graph.discover_from_logs(
        mock_logs, mock_service
    )
    print(
        f"  Source: {mock_service}"
    )
    print(
        f"  Discovered {len(discoveries)} "
        f"new dependencies:"
    )
    for d in discoveries:
        print(
            f"    {d['target']} "
            f"({d['confidence']}) — "
            f"{d['evidence'][:50]}"
        )
    print(
        "  (yaml not updated — test only)"
    )

    print("\nTask F OK")
