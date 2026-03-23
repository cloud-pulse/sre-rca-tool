import sys
import os
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

import subprocess
import json
import re
from dataclasses import dataclass
from core.logger import get_logger
from rich.console import Console
from rich.table import Table
from rich import box

log = get_logger("service_discovery")
console = Console()

@dataclass
class PodMatch:
    pod_name: str
    namespace: str
    image_name: str
    container_name: str
    confidence: int
    match_reason: str

class ServiceDiscovery:

    def __init__(self):
        self._pod_cache = []
        self._kubectl_available = None

    def _check_kubectl(self) -> bool:
        if self._kubectl_available is not None:
            return self._kubectl_available
        try:
            result = subprocess.run(
                ["kubectl", "cluster-info"],
                capture_output=True,
                text=True,
                timeout=5
            )
            self._kubectl_available = (
                result.returncode == 0
            )
        except Exception:
            self._kubectl_available = False
        return self._kubectl_available

    def scan_all_pods(self) -> list[dict]:
        if self._pod_cache:
            return self._pod_cache

        if not self._check_kubectl():
            log.debug(
                "kubectl not available "
                "for pod scanning"
            )
            return []

        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "pods",
                    "--all-namespaces",
                    "-o", "json"
                ],
                capture_output=True,
                text=True,
                timeout=20
            )
            if result.returncode != 0:
                log.debug(
                    f"kubectl get pods failed: "
                    f"{result.stderr[:100]}"
                )
                return []

            data = json.loads(result.stdout)
            pods = []
            for item in data.get("items", []):
                ns = (
                    item["metadata"]
                    .get("namespace", "default")
                )
                pod_name = (
                    item["metadata"]
                    .get("name", "")
                )
                for c in (
                    item["spec"]
                    .get("containers", [])
                ):
                    pods.append({
                        "pod_name": pod_name,
                        "namespace": ns,
                        "container_name": c.get("name", ""),
                        "image_name": c.get("image", ""),
                    })

            self._pod_cache = pods
            log.step(
                f"Scanned {len(pods)} containers"
                f" across all namespaces"
            )
            return pods

        except json.JSONDecodeError as e:
            log.debug(f"JSON parse error: {e}")
            return []
        except Exception as e:
            log.debug(f"Pod scan failed: {e}")
            return []

    def find_matches(self,
                     service_name: str,
                     top_k: int = 5
                     ) -> list[PodMatch]:
        pods = self.scan_all_pods()
        matches = {}

        svc_lower = service_name.lower()
        svc_parts = [
            p for p in svc_lower.split("-")
            if len(p) >= 3
        ]

        for pod in pods:
            image = pod["image_name"].lower()
            container = pod["container_name"].lower()
            namespace = pod["namespace"]

            # Extract image basename
            image_base = image.split("/")[-1]\
                .split(":")[0]

            confidence = 0
            reason = ""

            if (svc_lower == container or
                    svc_lower == image_base):
                confidence = 95
                reason = "exact name match"

            elif (svc_lower in image or
                  svc_lower in container):
                confidence = 85
                reason = f"'{svc_lower}' in image/container name"

            elif svc_parts and (
                svc_parts[0] in image or
                svc_parts[0] in container
            ):
                confidence = 70
                reason = f"'{svc_parts[0]}' in image/container name"

            else:
                for part in svc_parts:
                    if (part in image or
                            part in container):
                        confidence = 50
                        reason = f"'{part}' in image/container"
                        break

            if confidence < 40:
                continue

            key = f"{namespace}:{image_base}"
            if (key not in matches or
                    confidence > matches[key].confidence):
                matches[key] = PodMatch(
                    pod_name=pod["pod_name"],
                    namespace=namespace,
                    image_name=pod["image_name"],
                    container_name=pod["container_name"],
                    confidence=confidence,
                    match_reason=reason
                )

        results = sorted(
            matches.values(),
            key=lambda x: x.confidence,
            reverse=True
        )
        return results[:top_k]

    def prompt_for_namespace(
            self,
            service_name: str
    ) -> str | None:
        console.print()
        console.print(
            f"[bold yellow]⚠[/bold yellow] "
            f"[yellow]'{service_name}' not found"
            f" in services.yaml[/yellow]"
        )

        matches = []

        if self._check_kubectl():
            console.print(
                "[dim]Scanning cluster for "
                "matching containers...[/dim]"
            )
            with console.status(
                "[dim]Scanning...[/dim]",
                spinner="dots"
            ):
                matches = self.find_matches(
                    service_name
                )

            if matches:
                table = Table(
                    box=box.ROUNDED,
                    show_lines=True,
                    title=(
                        "Possible matches found"
                    )
                )
                table.add_column(
                    "#",
                    style="bold white",
                    width=3
                )
                table.add_column(
                    "Namespace",
                    style="cyan"
                )
                table.add_column(
                    "Image",
                    style="dim"
                )
                table.add_column(
                    "Container",
                    style="white"
                )
                table.add_column(
                    "Match",
                    justify="right"
                )

                for i, m in enumerate(
                    matches, 1
                ):
                    img = m.image_name
                    if len(img) > 35:
                        img = "..." + img[-32:]

                    conf_color = (
                        "bold green"
                        if m.confidence >= 80
                        else "bold yellow"
                        if m.confidence >= 60
                        else "dim white"
                    )
                    table.add_row(
                        str(i),
                        m.namespace,
                        img,
                        m.container_name,
                        f"[{conf_color}]{m.confidence}%[/{conf_color}]"
                    )

                console.print(table)
            else:
                console.print(
                    "[dim]No matching containers"
                    " found in cluster.[/dim]"
                )
        else:
            console.print(
                "[dim]kubectl not available — "
                "no cluster scan possible.[/dim]"
            )

        console.print()
        console.print(
            "  Enter a number from the list\n"
            "  or type the namespace directly\n"
            "  or type [bold red]cancel[/] "
            "to abort"
        )
        console.print()

        try:
            console.print(
                "[bold cyan]Namespace:[/bold cyan]"
                " ",
                end=""
            )
            answer = input().strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not answer:
            return None
        if answer.lower() == "cancel":
            console.print(
                "[dim]Cancelled.[/dim]"
            )
            return None

        # Number selection
        if answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(matches):
                chosen = matches[idx].namespace
                console.print(
                    f"[dim]Selected: "
                    f"{chosen}[/dim]"
                )
                return chosen
            else:
                console.print(
                    "[yellow]Number out of range."
                    " Using as namespace.[/yellow]"
                )
                return answer

        # Direct text input
        console.print(
            f"[dim]Using namespace: "
            f"{answer}[/dim]"
        )
        return answer

    def prompt_save_to_yaml(
            self,
            service_name: str,
            namespace: str
    ) -> bool:
        console.print()
        console.print(
            f"  Save [bold cyan]{service_name}"
            f"[/bold cyan] "
            f"(namespace: [dim]{namespace}[/dim])"
            f" to services.yaml?\n"
            f"  [bold green](y)[/bold green]"
            f" / [bold red](n)[/bold red]: ",
            end=""
        )
        try:
            answer = input().strip().lower()
            return answer in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False

if __name__ == "__main__":
    print("=== ServiceDiscovery Test ===\n")

    sd = ServiceDiscovery()

    print("--- Test 1: kubectl check ---")
    kubectl_ok = sd._check_kubectl()
    print(f"kubectl available: {kubectl_ok}")

    print("\n--- Test 2: Pod scan ---")
    pods = sd.scan_all_pods()
    print(f"Pods found: {len(pods)}")
    if pods:
        print(f"Sample: {pods[0]}")
    else:
        print(
            "(No pods — kubectl unavailable "
            "or no cluster running)"
        )

    print("\n--- Test 3: Match scoring ---")
    try:
        from core.service_graph import ServiceGraph
        graph = ServiceGraph()
        services = graph.get_all_service_names()
        if services and pods:
            target = services[0]
            print(f"Matching: '{target}'")
            matches = sd.find_matches(target)
            print(f"Matches: {len(matches)}")
            for m in matches:
                print(
                    f"  {m.namespace} | "
                    f"{m.container_name} | "
                    f"{m.confidence}% | "
                    f"{m.match_reason}"
                )
        elif not pods:
            print(
                "Skipped — no pods to match against"
            )
    except ImportError:
        print("Skipped — service_graph not available")

    print("\n--- Test 4: Unknown service ---")
    unknown = sd.find_matches(
        "totally-unknown-xyz-service-999"
    )
    print(
        f"Unknown service matches: "
        f"{len(unknown)} "
        f"(expect 0)"
    )

    print("\nTask R1 OK")

