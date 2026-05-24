import sys
import os
import re
from typing import List, Dict, Any
from core.logger import get_logger

log = get_logger("rag_engine")

import chromadb
from core.llm_provider import provider
from core.log_loader import LogLoader

# Allow imports to work when running this file directly
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RAGEngine:
    """RAG (Retrieval-Augmented Generation) engine for historical incident analysis.
    
    Indexes historical log files into ChromaDB for similarity search.
    """

    def __init__(self, historical_logs_dir: str):
        """Initialize RAG engine with ChromaDB and embedding model."""
        from flags import RAG_TOP_K as TOP_K_RETRIEVAL, CHROMA_DB_PATH
        
        self.historical_logs_dir = historical_logs_dir
        self.top_k = TOP_K_RETRIEVAL
        self.chroma_path = CHROMA_DB_PATH
        
        # Step 1 — Initialize ChromaDB persistent client
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        log.step(f"ChromaDB initialized at {self.chroma_path}")
        
        # Step 2 — Get or create collection with Cosine Distance Space
        self.collection = self.chroma_client.get_or_create_collection(
            name="sre_historical_incidents_v1",
            metadata={"hnsw:space": "cosine"}
        )
        log.step("Collection ready: sre_historical_incidents_v1")
        
        # Step 3 — Index historical logs
        self._index_historical_logs()
        # log.success("RAG engine ready.")

    def _extract_metadata_from_header(self, lines: List[str]) -> Dict[str, str]:
        """Extract resolution metadata from the comment header block."""
        metadata = {}
        current_key = None
        
        for line in lines:
            line = line.strip()
            if not line.startswith('#'):
                break  # End of header
            
            content = line[1:].strip()
            
            if ':' in content:
                key, value = content.split(':', 1)
                key = key.strip().lower().replace(' ', '_')
                value = value.strip()
                
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
                metadata[current_key] += ' ' + content
        
        return metadata

    def _extract_rca_analysis(self, lines: List[str]) -> str:
        """Extracts only the pure RCA Analysis section from a historical incident log."""
        content = "\n".join(lines)
        # Regex captures everything between the RCA Analysis header and the Evidence section
        match = re.search(r"## RCA Analysis\n(.*?)(?=\n## Evidence Sample|$)", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def _chunk_log(self, lines: List[str], chunk_size: int = 20, overlap: int = 5) -> List[str]:
        """Split log lines into overlapping text chunks."""
        log_lines = [line for line in lines if not line.strip().startswith('#')]
        if not log_lines:
            return []
        
        chunks = []
        start = 0
        
        while start < len(log_lines):
            end = min(start + chunk_size, len(log_lines))
            chunk_lines = log_lines[start:end]
            
            chunk_text = '\n'.join(chunk_lines).strip()
            if chunk_text:
                chunks.append(chunk_text)
            
            start += chunk_size - overlap
            if start >= end:
                break
        
        return chunks

    def _index_historical_logs(self):
        """Load and index all historical log files into ChromaDB."""
        loader = LogLoader()
        files = loader.load_directory(self.historical_logs_dir)
        
        existing = self.collection.get()
        already_indexed = set()
        if existing and 'metadatas' in existing:
            for metadata in existing['metadatas']:
                if metadata and 'source_file' in metadata:
                    already_indexed.add(metadata['source_file'])
        
        total_chunks = 0
        indexed_files = 0
        
        for filename, lines in files.items():
            if filename in already_indexed:
                log.step(f"Skipping {filename} (already indexed)")
                continue
            
            metadata = self._extract_metadata_from_header(lines)
            rca_analysis = self._extract_rca_analysis(lines)
            chunks = self._chunk_log(lines)
            
            # CRITICAL FIX: Inject the clean, historical analysis text as Chunk 0.
            # This matches the textual style used during IncidentRecorder queries.
            if rca_analysis:
                chunks.insert(0, f"[HISTORICAL ANALYSIS PAYLOAD]\n{rca_analysis}")
            
            if not chunks:
                log.step(f"Skipping {filename} (no chunks generated)")
                continue
            
            embeddings = provider.embed(chunks)
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
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas
            )
            
            log.step(f"Indexed {filename}: {len(chunks)} chunks")
            total_chunks += len(chunks)
            indexed_files += 1
        
        log.step(f"Total indexed: {total_chunks} chunks across {indexed_files} files")

    def retrieve(self, query_text: str, top_k: int = None) -> Dict[str, Any]:
        """Expose a structured retrieval method for the incident engine interface."""
        k = top_k or self.top_k
        return self.collection.query(query_texts=[query_text], n_results=k)

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
            log.error(f"Error getting collection stats: {e}")
            return {
                "total_chunks": 0,
                "files_indexed": [],
                "collection_name": "sre_historical_incidents"
            }


if __name__ == "__main__":
    # Self-test invocation context
    engine = RAGEngine("logs/historical")
    print(engine.get_collection_stats())
