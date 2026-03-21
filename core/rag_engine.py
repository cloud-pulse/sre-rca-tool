import logging
import warnings
import os

# Suppress sentence-transformers/transformers
# verbose load reports
logging.getLogger(
    "sentence_transformers"
).setLevel(logging.ERROR)
logging.getLogger(
    "transformers"
).setLevel(logging.ERROR)
warnings.filterwarnings(
    "ignore",
    message=".*position_ids.*"
)
warnings.filterwarnings(
    "ignore",
    category=FutureWarning
)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import os
import re
import sys
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer
import chromadb

# Allow imports to work when running this file directly
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.log_loader import LogLoader


class RAGEngine:
    """
    RAG (Retrieval-Augmented Generation) engine for historical incident analysis.
    
    Indexes historical log files into ChromaDB for similarity search.
    """

    def __init__(self, historical_logs_dir: str):
        """Initialize RAG engine with ChromaDB and embedding model."""
        from config import TOP_K_RETRIEVAL, CHROMA_DB_PATH, EMBEDDING_MODEL
        
        self.historical_logs_dir = historical_logs_dir
        self.top_k = TOP_K_RETRIEVAL
        self.chroma_path = CHROMA_DB_PATH
        self.embedding_model_name = EMBEDDING_MODEL
        
        # Step 1 — Load sentence-transformer model
        self.embedder = SentenceTransformer(self.embedding_model_name)
        print(f"Embedding model loaded: {self.embedding_model_name}")
        
        # Step 2 — Initialize ChromaDB persistent client
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        print(f"ChromaDB initialized at {self.chroma_path}")
        
        # Step 3 — Get or create collection
        self.collection = self.chroma_client.get_or_create_collection(
            name="sre_historical_incidents",
            metadata={"hnsw:space": "cosine"}
        )
        print("Collection ready: sre_historical_incidents")
        
        # Step 4 — Index historical logs
        self._index_historical_logs()
        print("RAG engine ready.")

    def _extract_metadata_from_header(self, lines: List[str]) -> Dict[str, str]:
        """
        Extract resolution metadata from the comment header block.
        
        Args:
            lines: List of log file lines
            
        Returns:
            Dictionary with metadata fields
        """
        metadata = {}
        current_key = None
        
        for line in lines:
            line = line.strip()
            if not line.startswith('#'):
                break  # End of header
            
            # Remove the # prefix
            content = line[1:].strip()
            
            # Check if this is a new key
            if ':' in content:
                key, value = content.split(':', 1)
                key = key.strip().lower().replace(' ', '_')
                value = value.strip()
                
                # Map to our expected keys
                key_mapping = {
                    'incident': 'incident_type',
                    'date': 'date',
                    'severity': 'severity',
                    'root_cause': 'root_cause',
                    'resolution': 'resolution',
                    'status': 'status'
                }
                
                if key in key_mapping:
                    current_key = key_mapping[key]
                    metadata[current_key] = value
                else:
                    current_key = None
            elif current_key and content:
                # Continuation of previous multi-line value
                metadata[current_key] += ' ' + content
        
        return metadata

    def _chunk_log(self, lines: List[str], chunk_size: int = 20, overlap: int = 5) -> List[str]:
        """
        Split log lines into overlapping text chunks.
        
        Args:
            lines: List of log lines
            chunk_size: Number of lines per chunk
            overlap: Number of overlapping lines between chunks
            
        Returns:
            List of chunk strings
        """
        # Filter out comment lines (metadata)
        log_lines = [line for line in lines if not line.strip().startswith('#')]
        
        if not log_lines:
            return []
        
        chunks = []
        start = 0
        
        while start < len(log_lines):
            end = min(start + chunk_size, len(log_lines))
            chunk_lines = log_lines[start:end]
            
            # Join lines and check if chunk has content
            chunk_text = '\n'.join(chunk_lines).strip()
            if chunk_text:
                chunks.append(chunk_text)
            
            # Move start position with overlap
            start += chunk_size - overlap
            
            # Prevent infinite loop
            if start >= end:
                break
        
        return chunks

    def _index_historical_logs(self):
        """Load and index all historical log files into ChromaDB."""
        # Step 1: Load all .log files
        loader = LogLoader()
        files = loader.load_directory(self.historical_logs_dir)
        
        # Step 2: Check what is already indexed
        existing = self.collection.get()
        already_indexed = set()
        if existing and 'metadatas' in existing:
            for metadata in existing['metadatas']:
                if metadata and 'source_file' in metadata:
                    already_indexed.add(metadata['source_file'])
        
        total_chunks = 0
        indexed_files = 0
        
        # Step 3: For each file not yet indexed
        for filename, lines in files.items():
            if filename in already_indexed:
                print(f"Skipping {filename} (already indexed)")
                continue
            
            # a. Extract metadata from header
            metadata = self._extract_metadata_from_header(lines)
            
            # b. Chunk the log lines
            chunks = self._chunk_log(lines)
            
            if not chunks:
                print(f"Skipping {filename} (no chunks generated)")
                continue
            
            # c. Generate embeddings for all chunks at once
            embeddings = self.embedder.encode(chunks)
            
            # d. Add to ChromaDB collection
            ids = [f"{filename}_chunk_{i}" for i in range(len(chunks))]
            
            metadatas = []
            for i in range(len(chunks)):
                chunk_metadata = {
                    "source_file": filename,
                    "chunk_index": i,
                    "incident_type": metadata.get("incident_type", ""),
                    "resolution": metadata.get("resolution", ""),
                    "severity": metadata.get("severity", ""),
                    "date": metadata.get("date", "")
                }
                metadatas.append(chunk_metadata)
            
            self.collection.add(
                ids=ids,
                embeddings=embeddings.tolist(),
                documents=chunks,
                metadatas=metadatas
            )
            
            # e. Print progress
            print(f"Indexed {filename}: {len(chunks)} chunks")
            total_chunks += len(chunks)
            indexed_files += 1
        
        # Step 5: Print total summary
        print(f"Total indexed: {total_chunks} chunks across {indexed_files} files")

    def get_collection_stats(self) -> Dict[str, Any]:
        """
        Return stats about what is currently indexed.
        
        Returns:
            Dictionary with collection statistics
        """
        try:
            result = self.collection.get()
            total_chunks = len(result.get('ids', []))
            
            files_indexed = set()
            if 'metadatas' in result:
                for metadata in result['metadatas']:
                    if metadata and 'source_file' in metadata:
                        files_indexed.add(metadata['source_file'])
            
            return {
                "total_chunks": total_chunks,
                "files_indexed": sorted(list(files_indexed)),
                "collection_name": "sre_historical_incidents"
            }
        except Exception as e:
            print(f"Error getting collection stats: {e}")
            return {
                "total_chunks": 0,
                "files_indexed": [],
                "collection_name": "sre_historical_incidents"
            }


    def retrieve(self, query_text: str, top_k: int = None) -> List[Dict[str, Any]]:
        """
        Find the most similar historical log chunks to the given query_text.
        
        Args:
            query_text: The query text to search for
            top_k: Number of results to return (uses self.top_k if None)
            
        Returns:
            List of retrieved results with metadata
        """
        if top_k is None:
            top_k = self.top_k
        
        # Step 1: Embed the query text
        query_embedding = self.embedder.encode([query_text])
        
        # Step 2: Query ChromaDB collection
        results = self.collection.query(
            query_embeddings=[query_embedding[0].tolist()],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        
        # Step 3: Build result list
        retrieved = []
        if results and 'metadatas' in results and results['metadatas']:
            for i, metadata in enumerate(results['metadatas'][0]):
                distance = results['distances'][0][i] if 'distances' in results else 0.0
                similarity_score = round((1 - distance) * 100, 1)
                similarity_score = max(0, min(100, similarity_score))  # Clamp
                
                result = {
                    "source_file": metadata.get("source_file", ""),
                    "chunk": results['documents'][0][i] if 'documents' in results else "",
                    "incident_type": metadata.get("incident_type", ""),
                    "resolution": metadata.get("resolution", ""),
                    "severity": metadata.get("severity", ""),
                    "date": metadata.get("date", ""),
                    "distance": distance,
                    "similarity_score": similarity_score
                }
                retrieved.append(result)
        
        # Step 4: Deduplicate by source_file (keep best per file)
        best_per_file = {}
        for result in retrieved:
            source_file = result["source_file"]
            if source_file not in best_per_file or \
               result["similarity_score"] > best_per_file[source_file]["similarity_score"]:
                best_per_file[source_file] = result
        
        # Step 5: Sort by similarity_score descending
        retrieved = sorted(best_per_file.values(), 
                          key=lambda x: x["similarity_score"], 
                          reverse=True)
        
        # Step 6: Print retrieval summary
        print(f"RAG retrieved {len(retrieved)} historical incidents:")
        for result in retrieved:
            print(f"  {result['source_file']} — {result['similarity_score']}% match "
                  f"({result['incident_type']})")
        
        return retrieved

    def format_retrieved_context(self, retrieved: List[Dict[str, Any]], 
                                max_chunk_chars: int = 800) -> str:
        """
        Format retrieved historical incidents as a clean string for LLM prompt injection.
        
        Args:
            retrieved: List of retrieved results
            max_chunk_chars: Maximum characters for chunk text
            
        Returns:
            Formatted context string
        """
        if not retrieved:
            return "No similar historical incidents found."
        
        output = []
        output.append("=== RETRIEVED HISTORICAL CONTEXT ===")
        output.append(f"{len(retrieved)} similar past incidents found")
        output.append("")
        
        for i, result in enumerate(retrieved, 1):
            output.append(f"=== HISTORICAL INCIDENT {i} ===")
            output.append(f"Source       : {result['source_file']}")
            output.append(f"Date         : {result['date']}")
            output.append(f"Severity     : {result['severity']}")
            output.append(f"Incident type: {result['incident_type']}")
            output.append(f"Similarity   : {result['similarity_score']}% match")
            output.append("")
            
            # Truncate chunk text
            chunk_text = result['chunk']
            if len(chunk_text) > max_chunk_chars:
                chunk_text = chunk_text[:max_chunk_chars] + "...[truncated]"
            
            output.append("Relevant log excerpt:")
            output.append(chunk_text)
            output.append("")
            
            output.append("How it was resolved:")
            output.append(result['resolution'])
            output.append("─" * 50)
            output.append("")
        
        output.append("=== END OF HISTORICAL CONTEXT ===")
        
        return "\n".join(output)

    def get_best_match(self, retrieved: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        """
        Return the single best matching historical incident.
        
        Args:
            retrieved: List of retrieved results
            
        Returns:
            Best match dict or None if empty
        """
        if not retrieved:
            return None
        return max(retrieved, key=lambda x: x["similarity_score"])

    def is_known_pattern(self, retrieved: List[Dict[str, Any]], 
                        threshold: float = 60.0) -> bool:
        """
        Check if the best match has similarity score >= threshold.
        
        Args:
            retrieved: List of retrieved results
            threshold: Similarity threshold (default 60%)
            
        Returns:
            True if known pattern detected
        """
        best = self.get_best_match(retrieved)
        if not best:
            return False
        return best["similarity_score"] >= threshold


if __name__ == "__main__":
    from config import HISTORICAL_LOGS_DIR
    from core.log_loader import LogLoader
    from core.log_processor import LogProcessor
    from core.context_builder import ContextBuilder
    from core.resource_collector import ResourceCollector

    print("=== Task 13 — RAG Retrieval Test ===\n")

    print("--- Test 1: Initialize RAG engine ---")
    rag = RAGEngine(HISTORICAL_LOGS_DIR)
    stats = rag.get_collection_stats()
    print(f"Chunks indexed: {stats['total_chunks']}")
    print(f"Files indexed : {stats['files_indexed']}")

    print("\n--- Test 2: Retrieve with DB error query ---")
    db_query = (
        "database connection timeout pool exhausted "
        "payment service failed"
    )
    results = rag.retrieve(db_query, top_k=3)
    print(f"Retrieved {len(results)} results:")
    for r in results:
        print(f"  {r['source_file']}: "
              f"{r['similarity_score']}% — "
              f"{r['incident_type']}")

    print("\n--- Test 3: Retrieve with real log context ---")
    loader = LogLoader()
    processor = LogProcessor()
    collector = ResourceCollector()
    builder = ContextBuilder()

    lines = loader.load("logs/test.log")
    entries = processor.process(lines)
    filtered = processor.filter_by_severity(
        entries, "ERROR"
    )
    summary = processor.get_summary(entries)
    resources = collector.get_mock_resources(
        summary["services"]
    )
    context = builder.build(filtered, resources)

    results_real = rag.retrieve(
        context["formatted_logs"], top_k=3
    )
    print(f"Retrieved {len(results_real)} results "
          f"from real log context")
    for r in results_real:
        print(f"  {r['source_file']}: "
              f"{r['similarity_score']}%")

    print("\n--- Test 4: Format retrieved context ---")
    formatted = rag.format_retrieved_context(results_real)
    print(formatted[:600])
    print("...(truncated for display)")

    print("\n--- Test 5: Best match ---")
    best = rag.get_best_match(results_real)
    if best:
        print(f"Best match: {best['source_file']} "
              f"at {best['similarity_score']}%")
        print(f"Incident  : {best['incident_type']}")

    print("\n--- Test 6: Known pattern check ---")
    known = rag.is_known_pattern(results_real)
    print(f"Is known pattern (>=60%): {known}")

    print("\n--- Test 7: OOM query (different incident) ---")
    oom_query = (
        "memory limit exceeded OOMKilled pod restarting "
        "memory usage 90 percent"
    )
    oom_results = rag.retrieve(oom_query, top_k=3)
    print("OOM query top result:")
    if oom_results:
        print(f"  {oom_results[0]['source_file']}: "
              f"{oom_results[0]['similarity_score']}% — "
              f"{oom_results[0]['incident_type']}")
        print("  (should prefer incident_002.log for OOM)")

    print("\nTask 13 OK")