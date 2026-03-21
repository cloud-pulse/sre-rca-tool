import os
import glob

class LogLoader:
    def load(self, filepath: str) -> list[str]:
        if not os.path.exists(filepath):
            print(f"ERROR: File not found: {filepath}")
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
                print(f"ERROR: Encoding error failed fallback for {filepath}: {e}")
                return []
        except PermissionError:
            print(f"ERROR: Permission denied: {filepath}")
            return []
        except Exception as e:
            print(f"ERROR: Failed to read {filepath}: {e}")
            return []

        extracted_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped:  # skips empty lines and whitespace only
                extracted_lines.append(stripped)
            
        if not extracted_lines:
            print(f"WARNING: Empty file: {filepath}")
            return []
            
        print(f"Loaded {len(extracted_lines)} lines from {filepath}")
        return extracted_lines

    def load_directory(self, dirpath: str) -> dict[str, list[str]]:
        results = {}
        if not os.path.exists(dirpath):
            print(f"ERROR: Directory not found: {dirpath}")
            return results
            
        if not os.path.isdir(dirpath):
            print(f"ERROR: Path is not a directory: {dirpath}")
            return results

        log_files = glob.glob(os.path.join(dirpath, "*.log"))
        
        for f in log_files:
            lines = self.load(f)
            if lines:
                fname = os.path.basename(f)
                results[fname] = lines
                
        if results:
            print(f"Loaded {len(results)} files from {dirpath}")
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
