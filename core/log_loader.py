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

import glob
import subprocess
from core.logger import get_logger

log = get_logger("log_loader")

class LogLoader:
    def load(self, filepath: str) -> list[str]:
        if not os.path.exists(filepath):
            log.error(f"File not found: {filepath}")
            return []
            
        try:
            # First attempt with utf-8
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                # Retry with latin-1
                with open(filepath, 'r', encoding='latin-1') as f:
                    content = f.read()
            except Exception as e:
                log.error(f"Encoding error failed fallback for {filepath}: {e}")
                return []
        except PermissionError:
            log.error(f"Permission denied: {filepath}")
            return []
        except Exception as e:
            log.error(f"Failed to read {filepath}: {e}")
            return []

        extracted_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped:  # skips empty lines and whitespace only
                extracted_lines.append(stripped)
            
        if not extracted_lines:
            log.warn(f"Empty file: {filepath}")
            return []
            
        from core.log_cleaner import LogCleaner
        _cleaner = LogCleaner()
        _original = extracted_lines
        extracted_lines = _cleaner.clean(extracted_lines)
        stats = _cleaner.get_stats(_original, extracted_lines)
        log.info(f"[dim]Cleaned: {stats['removed_count']} lines removed ({stats['removal_percent']}%)[/dim]")

        log.step(f"Loaded {len(extracted_lines)} lines from {filepath}")
        return extracted_lines

    def load_directory(self, dirpath: str) -> dict[str, list[str]]:
        results = {}
        if not os.path.exists(dirpath):
            log.error(f"Directory not found: {dirpath}")
            return results
            
        if not os.path.isdir(dirpath):
            log.error(f"Path is not a directory: {dirpath}")
            return results

        log_files = glob.glob(os.path.join(dirpath, "*.log"))
        
        for f in log_files:
            lines = self.load(f)
            if lines:
                fname = os.path.basename(f)
                results[fname] = lines
                
        if results:
            log.step(f"Loaded {len(results)} files from {dirpath}")
        return results

    def get_file_metadata(self, filepath: str) -> dict:
        metadata = {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "size_bytes": 0,
            "line_count": 0,
            "exists": False
        }
        
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            return metadata
            
        metadata["exists"] = True
        try:
            metadata["size_bytes"] = os.path.getsize(filepath)
            
            # Read line count carefully honoring encoding fallbacks
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(filepath, 'r', encoding='latin-1') as f:
                    content = f.read()
                    
            metadata["line_count"] = sum(1 for line in content.splitlines() if line.strip())
        except Exception:
            pass
            
        return metadata

    def get_pod_names(self,
                      namespace: str = "default",
                      service: str = None
                      ) -> list[str]:
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    namespace,
                    "--no-headers",
                ],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            log.error(
                "kubectl not found. Install kubectl or set SOURCE_KUBERNETES=false"
            )
            return []

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            log.error(f"Failed to list pods: {stderr}")
            if "namespaces" in stderr and "not found" in stderr:
                log.error(f"Namespace {namespace} not found")
            return []

        pod_names = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if not parts:
                continue
            pod_name = parts[0]
            if service:
                if service in pod_name:
                    pod_names.append(pod_name)
            else:
                pod_names.append(pod_name)

        return pod_names

    def load_from_kubectl(self,
                          namespace: str = "default",
                          service: str = None,
                          tail: int = 100
                          ) -> list[str]:
        pod_names = self.get_pod_names(namespace=namespace, service=service)

        if not pod_names:
            log.warn(f"No pods in {namespace}")
            return []

        combined = []
        for pod in pod_names:
            try:
                result = subprocess.run(
                    [
                        "kubectl",
                        "logs",
                        pod,
                        "-n",
                        namespace,
                        f"--tail={tail}",
                        "--timestamps=true",
                    ],
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                log.error(
                    "kubectl not found. Install kubectl or set SOURCE_KUBERNETES=false"
                )
                return []

            if result.returncode != 0:
                log.debug(
                    f"Failed to fetch logs for pod {pod}: {result.stderr.strip()}"
                )
                continue

            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            for line in lines:
                combined.append(f"[{pod}] {line}")

        if not combined:
            log.warn(f"No logs fetched from pods in {namespace}")
            return []

        # Attempt timestamp sort: lines start with [pod] TIMESTAMP ...
        try:
            def sort_key(l):
                parts = l.split(" ", 3)
                if len(parts) >= 3 and parts[2].replace("T", " "):
                    return parts[2]
                return l

            combined = sorted(combined, key=sort_key)
        except Exception:
            pass

        from core.log_cleaner import LogCleaner
        _cleaner = LogCleaner()
        _original = combined
        combined = _cleaner.clean(combined)
        stats = _cleaner.get_stats(_original, combined)
        log.info(f"[dim]Cleaned: {stats['removed_count']} lines removed ({stats['removal_percent']}%)[/dim]")

        log.step(
            f"Fetched {len(combined)} log lines from {len(pod_names)} pods in {namespace}"
        )
        return combined

    def load_auto(self,
                  filepath: str = None,
                  namespace: str = "default",
                  service: str = None,
                  tail: int = 100) -> list[str]:
        from flags import USE_KUBERNETES
        if USE_KUBERNETES:
            log.info(
                "[dim]Source: Kubernetes "
                f"(namespace={namespace})[/dim]"
            )
            return self.load_from_kubectl(
                namespace=namespace,
                service=service,
                tail=tail,
            )

        if not filepath:
            log.error(
                "No log file specified and SOURCE_KUBERNETES=false"
            )
            return []

        log.info(f"[dim]Source: file ({filepath})[/dim]")
        return self.load(filepath)

    def load_service_logs(self, service_name: str, fallback_log: str = "logs/test.log") -> list[str]:
        target = f"logs/services/{service_name}.log"
        if os.path.exists(target):
            log.info(f"Loading per-service log for {service_name}")
            return self.load(target)
            
        log.info(f"Per-service log not found for {service_name}, filtering {fallback_log}")
        fallback_lines = self.load(fallback_log)
        filtered = [l for l in fallback_lines if service_name in l]
        
        if not filtered:
            log.warn(f"No logs found for {service_name}")
            return filtered
            
        from core.log_cleaner import LogCleaner
        _cleaner = LogCleaner()
        _original = filtered
        filtered = _cleaner.clean(filtered)
        stats = _cleaner.get_stats(_original, filtered)
        log.info(f"[dim]Cleaned: {stats['removed_count']} lines removed ({stats['removal_percent']}%)[/dim]")

        return filtered

    def load_container_logs(self, service_name: str, container_name: str, fallback_log: str = "logs/test.log") -> list[str]:
        target = f"logs/services/{service_name}-{container_name}.log"
        if os.path.exists(target):
            return self.load(target)
            
        svc_logs = self.load_service_logs(service_name, fallback_log)
        filtered = [l for l in svc_logs if container_name in l]
        if filtered:
            return filtered
            
        return svc_logs

    def load_all_service_logs(self, service_names: list[str], fallback_log: str = "logs/test.log") -> dict[str, list[str]]:
        results = {}
        for svc in service_names:
            results[svc] = self.load_service_logs(svc, fallback_log)
        return results

    def load_mock_kubectl(self, resource_type: str, scenario: str) -> str:
        target = f"logs/mock/kubectl/{resource_type}/{scenario}.txt"
        if os.path.exists(target):
            try:
                with open(target, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                log.warn(f"Error reading mock file {target}: {e}")
                return ""
                
        log.warn(f"Mock file not found: {target}")
        return ""


if __name__ == "__main__":
    loader = LogLoader()

    print("--- Test 1: Load test.log ---")
    lines = loader.load("logs/test.log")
    print(f"Lines loaded: {len(lines)}")
    if lines:
        print(f"First line: {lines[0]}")
        print(f"Last line:  {lines[-1]}")

    print("\n--- Test 2: Load historical directory ---")
    all_files = loader.load_directory("logs/historical")
    for fname, flines in all_files.items():
        print(f"  {fname}: {len(flines)} lines")

    print("\n--- Test 3: File metadata ---")
    meta = loader.get_file_metadata("logs/test.log")
    print(f"  Metadata: {meta}")

    print("\n--- Test 4: Missing file handling ---")
    missing = loader.load("logs/does_not_exist.log")
    print(f"  Returned: {missing}")

    print("\nTask 6 OK")

    print("=== Task D — Source Toggle Test ===\n")

    print("--- Test 1: load_auto file mode ---")
    print("(SOURCE_KUBERNETES=false)")
    lines = loader.load_auto(filepath="logs/test.log")
    print(f"Loaded {len(lines)} lines from file")
    if lines:
        print(f"First line: {lines[0][:60]}")

    print("\n--- Test 2: get_pod_names ---")
    print("(requires kubectl + cluster)")
    try:
        pods = loader.get_pod_names(namespace="default")
        if pods:
            print(f"Found pods: {pods}")
        else:
            print(
                "No pods found or kubectl not available (expected "
                "if no cluster running)"
            )
    except Exception as e:
        print(f"kubectl not available: {e}")
        print("(OK — file mode still works)")

    print("\n--- Test 3: load_from_kubectl ---")
    print("(requires kubectl + cluster)")
    try:
        k8s_lines = loader.load_from_kubectl(namespace="default", tail=10)
        if k8s_lines:
            print(f"Fetched {len(k8s_lines)} lines from kubectl")
        else:
            print(
                "No lines fetched (no cluster running — OK)"
            )
    except Exception as e:
        print(f"kubectl error: {e}")

    print("\nTask D — Log Loader OK")
