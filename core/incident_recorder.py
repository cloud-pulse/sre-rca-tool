import os
import re
import shutil
import datetime
from core.logger import get_logger

log = get_logger("incident_recorder")


class IncidentRecorder:
    SIMILARITY_THRESHOLD = 0.72
    HISTORICAL_DIR = "logs/historical"

    def __init__(self, rag_engine=None):
        self._rag = rag_engine
        self._query_method = None

    # ─────────────────────────────────────────────────────────────────────
    # RAG engine — lazy load + dimension-mismatch auto-heal
    # ─────────────────────────────────────────────────────────────────────

    def _get_rag_engine(self, after_purge: bool = False):
        """
        Lazy-load RAGEngine. If ChromaDB raises a dimension mismatch at
        ANY point (not just init), call _purge_and_reload() which wipes
        the stale DB and returns a fresh engine.
        """
        if self._rag is not None:
            return self._rag
        try:
            from core.rag_engine import RAGEngine
            self._rag = RAGEngine(self.HISTORICAL_DIR)
            self._query_method = getattr(
                self._rag, "retrieve", getattr(self._rag, "query", None)
            )
            return self._rag
        except Exception as e:
            if _is_dim_error(e) and not after_purge:
                return self._purge_and_reload()
            log.error(f"RAGEngine init failed: {e}")
            return None

    def _purge_and_reload(self):
        """Delete the stale ChromaDB folder and reinitialise from scratch."""
        try:
            from flags import CHROMA_DB_PATH
        except ImportError:
            CHROMA_DB_PATH = ".chromadb"

        log.debug(
            f"Dimension mismatch detected — purging stale ChromaDB at '{CHROMA_DB_PATH}'..."
        )
        try:
            # Close existing Chroma handles first
            try:
                if self._rag and hasattr(self._rag, "client"):
                    try:
                        self._rag.client.reset()
                    except Exception:
                        pass

                self._rag = None
                self._query_method = None

            except Exception as e:
                log.warn(f"Failed to close Chroma client cleanly: {e}")

            import gc
            gc.collect()

            # Small delay for Windows file unlock
            import time
            time.sleep(2)

            if os.path.exists(CHROMA_DB_PATH):
                shutil.rmtree(CHROMA_DB_PATH, ignore_errors=True)
                log.debug(f"Purged: {CHROMA_DB_PATH}")
        except Exception as e:
            log.error(f"Purge failed: {e}")
            return None

        # Reset cached instance so _get_rag_engine re-initialises cleanly
        self._rag = None
        self._query_method = None
        return self._get_rag_engine(after_purge=True)

    # ─────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────

    def check_and_save(self, analysis: str, service: str, lines: list[str]) -> dict:
        similarity = self._query_similarity(analysis)

        if similarity >= self.SIMILARITY_THRESHOLD:
            log.info(
                f"Known incident for '{service}' "
                f"(similarity={similarity:.1%} >= {self.SIMILARITY_THRESHOLD:.0%}). Skipping."
            )
            return {
                "saved": False,
                "incident_id": "",
                "filepath": "",
                "embedded": False,
                "similarity_score": similarity,
                "reason": "known_incident",
            }

        incident_id = self._generate_incident_id()
        content = self._build_incident_text(incident_id, analysis, service, lines)
        filepath = self._save_to_disk(incident_id, content)

        embedded = False
        if filepath:
            embedded = self._embed_in_chromadb(incident_id, analysis, service)

        self._print_new_incident(incident_id, service, similarity, filepath, embedded)

        saved = bool(filepath)
        return {
            "saved": saved,
            "incident_id": incident_id if saved else "",
            "filepath": filepath if saved else "",
            "embedded": embedded,
            "similarity_score": similarity,
            "reason": "new_incident",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Similarity query
    # ─────────────────────────────────────────────────────────────────────

    def _query_similarity(self, analysis: str) -> float:
        try:
            rag = self._get_rag_engine()
            if rag is None or not hasattr(rag, "collection"):
                log.warn("RAGEngine unavailable — treating as new incident.")
                return 0.0

            clean_query = self._sanitize(analysis)
            if not clean_query.strip():
                return 0.0

            # CRITICAL: use the same provider.embed() that _embed_in_chromadb uses
            # Never use query_texts — ChromaDB would embed with a different model
            from core.llm_provider import provider
            try:
                embeddings = provider.embed([clean_query])
            except Exception as e:
                log.warn(f"Embedding failed during similarity query: {e}")
                return 0.0

            if not embeddings or not embeddings[0]:
                return 0.0

            try:
                results = rag.collection.query(
                    query_embeddings=[embeddings[0]],
                    n_results=1,
                    include=["distances"],
                )
            except Exception as e:
                if _is_dim_error(e):
                    log.warn("Dimension mismatch at query — purging DB.")
                    rag = self._purge_and_reload()
                    return 0.0
                log.warn(f"ChromaDB query failed: {e}")
                return 0.0

            # Extract distance
            nested = results.get("distances", [])
            if not nested or not nested[0]:
                return 0.0

            raw_dist = float(nested[0][0])
            space = "cosine"
            if hasattr(rag, "collection") and rag.collection.metadata:
                space = rag.collection.metadata.get("hnsw:space", "cosine")

            if space == "cosine":
                # ChromaDB cosine distance is in [0, 1] not [0, 2]
                similarity = max(0.0, min(1.0, 1.0 - raw_dist))
            else:
                similarity = max(0.0, min(1.0, 1.0 / (1.0 + raw_dist)))

            log.debug(f"Similarity query: dist={raw_dist:.4f} space={space} sim={similarity:.1%}")
            return similarity

        except Exception as e:
            if _is_dim_error(e):
                log.error("Dimension mismatch in ChromaDB.")
            else:
                log.warn(f"Similarity query failed: {e}")
            return 0.0


    # ─────────────────────────────────────────────────────────────────────
    # Disk + ChromaDB persistence
    # ─────────────────────────────────────────────────────────────────────

    def _save_to_disk(self, incident_id: str, content: str) -> str:
        try:
            os.makedirs(self.HISTORICAL_DIR, exist_ok=True)
            filepath = os.path.join(self.HISTORICAL_DIR, f"{incident_id}.log")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            log.debug(f"Saved to disk: {filepath}")
            return filepath
        except Exception as e:
            log.error(f"Disk save failed: {e}")
            return ""

    def _embed_in_chromadb(
        self, incident_id: str, analysis: str, service: str
    ) -> bool:
        """
        Embed the cleaned analysis narrative into ChromaDB.

        IMPORTANT: we embed only the sanitized analysis (not raw kubectl evidence)
        so the vector space stays consistent with what _query_similarity searches.
        """
        try:
            rag = self._get_rag_engine()
            if rag is None or not hasattr(rag, "collection"):
                log.warn("RAGEngine or collection unavailable — skipping embed.")
                return False

            from core.llm_provider import provider

            clean = self._sanitize(analysis)
            lines = [l for l in clean.splitlines() if l.strip()]
            if not lines:
                log.warn(f"Nothing to embed for {incident_id}")
                return False

            # 10-line chunks — smaller than before to avoid token limits
            chunks = ["\n".join(lines[i: i + 10]) for i in range(0, len(lines), 10)]

            try:
                embeddings = provider.embed(chunks)
            except Exception as e:
                if _is_dim_error(e):
                    log.error(
                        f"Embedding dimension mismatch for {incident_id}. "
                        "ChromaDB expects a different vector size than what the current "
                        "embedding model produces. Purging DB and retrying..."
                    )
                    rag = self._purge_and_reload()
                    if rag is None:
                        return False
                    embeddings = provider.embed(chunks)
                else:
                    log.error(f"Embedding call failed: {e}")
                    return False

            today = datetime.datetime.now().strftime("%Y-%m-%d")
            ids = [f"{incident_id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [
                {
                    "source_file": f"{incident_id}.log",
                    "chunk_index": i,
                    "incident_type": "auto-saved",
                    "resolution": "",
                    "severity": "",
                    "date": today,
                    "service": service,
                    "auto_saved": "true",
                }
                for i in range(len(chunks))
            ]

            try:
                rag.collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=metadatas,
                )
            except Exception as e:
                if _is_dim_error(e):
                    log.error(
                        f"ChromaDB rejected embed for {incident_id} — dimension mismatch "
                        "even after purge. Check that LLM_EMBEDDING_MODEL in .env matches "
                        "the model used to build your existing historical index."
                    )
                    return False
                raise

            log.debug(f"Embedded {len(chunks)} chunks for {incident_id}")
            return True

        except Exception as e:
            log.error(f"embed_in_chromadb failed for {incident_id}: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _sanitize(self, text: str) -> str:
        """Strip noise variables so semantic search focuses on concepts."""
        text = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?', '', text)
        text = re.sub(r'0x[0-9a-fA-F]+', '0xHEX', text)
        text = re.sub(
            r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
            'UUID', text
        )
        return text.strip()

    def _generate_incident_id(self) -> str:
        return f"incident_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _build_incident_text(
        self, incident_id: str, analysis: str, service: str, lines: list[str]
    ) -> str:
        sample = "\n".join(lines[:50])
        return (
            f"# Incident: {incident_id} (auto-saved)\n"
            f"# Service: {service}\n"
            f"# Timestamp: {datetime.datetime.now().isoformat()}\n"
            f"# Lines analysed: {len(lines)}\n\n"
            f"## RCA Analysis\n{analysis}\n\n"
            f"## Evidence Sample (first 50 lines)\n{sample}\n"
        )

    def _print_new_incident(
        self,
        incident_id: str,
        service: str,
        similarity: float,
        filepath: str,
        embedded: bool,
    ) -> None:
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
            from rich import box

            c = Console()
            t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("", style="bold cyan", width=16)
            t.add_column("", style="white")
            t.add_row("Incident ID", f"[yellow]{incident_id}[/yellow]")
            t.add_row("Service", service)
            t.add_row("Similarity", f"{similarity:.1%}  (threshold {self.SIMILARITY_THRESHOLD:.0%})")
            t.add_row("Saved to", f"[green]{filepath or 'FAILED'}[/green]")
            t.add_row(
                "Embedded",
                "[bold green]Yes[/bold green]"
                if embedded
                else "[bold red]No — embedding failed[/bold red]",
            )
            c.print(
                Panel(
                    t,
                    title="[bold gold3]⚡ New Incident Recorded[/bold gold3]",
                    border_style="gold3",
                    padding=(0, 1),
                )
            )
        except Exception:
            print(f"\n[NEW INCIDENT] {incident_id} | {service} | sim={similarity:.1%}")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helper
# ─────────────────────────────────────────────────────────────────────────────

def _is_dim_error(exc: Exception) -> bool:
    return "dimension" in str(exc).lower()