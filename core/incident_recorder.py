import os
import datetime
from core.logger import get_logger

log = get_logger("incident_recorder")

class IncidentRecorder:
    SIMILARITY_THRESHOLD = 0.40   # save if similarity < 40%
    HISTORICAL_DIR = "logs/historical"
    
    def check_and_save(self, analysis: str, service: str, lines: list[str]) -> dict:
        similarity = 0.0
        try:
            from core.rag_engine import RAGEngine
            rag = RAGEngine("logs/historical")
            results = None
            if hasattr(rag, "query"):
                results = rag.query(analysis, n_results=1)
            elif hasattr(rag, "retrieve"):
                # fallback for current rag_engine implementation
                results = rag.retrieve(analysis, top_k=1)

            if results and len(results) > 0:
                first = results[0]
                if 'distance' in first:
                    similarity = 1.0 - float(first['distance'])
                elif 'score' in first:
                    similarity = float(first['score'])
                elif 'similarity_score' in first:
                    similarity = float(first['similarity_score']) / 100.0
                else:
                    similarity = 0.0
            else:
                similarity = 0.0
        except Exception as e:
            log.warn(f"RAGEngine query failed: {e}")
            similarity = 0.0

        if similarity >= self.SIMILARITY_THRESHOLD:
            log.info("Known incident detected.")
            return {
                "saved": False,
                "incident_id": "",
                "filepath": "",
                "embedded": False,
                "similarity_score": similarity,
                "reason": "known_incident"
            }

        incident_id = self._generate_incident_id()
        content = self._build_incident_text(incident_id, analysis, service, lines)
        filepath = self._save_to_disk(incident_id, content)
        
        embedded = False
        if filepath:
            embedded = self._embed_in_chromadb(incident_id, content, service)
            
        print(f"\n[NEW INCIDENT] Saving new incident: {incident_id}")
        print(f"  Service:    {service}")
        print(f"  Similarity: {similarity:.1%} (below {self.SIMILARITY_THRESHOLD:.0%} threshold)")
        print(f"  Saved to:   {filepath}")
        print(f"  Embedded:   {'yes' if embedded else 'no (embedding failed)'}\n")

        saved = bool(filepath)
        return {
            "saved": saved,
            "incident_id": incident_id if saved else "",
            "filepath": filepath if saved else "",
            "embedded": embedded,
            "similarity_score": similarity,
            "reason": "new_incident"
        }

    def _generate_incident_id(self) -> str:
        return f"incident_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _build_incident_text(self, incident_id: str, analysis: str, service: str, lines: list[str]) -> str:
        lines_text = chr(10).join(lines[:50])
        return f"""# Incident: {incident_id} (auto-saved)
# Service: {service}
# Timestamp: {datetime.datetime.now().isoformat()}
# Lines analysed: {len(lines)}

## RCA Analysis
{analysis}

## Log Sample (first 50 lines)
{lines_text}"""

    def _save_to_disk(self, incident_id: str, content: str) -> str:
        try:
            os.makedirs(self.HISTORICAL_DIR, exist_ok=True)
            filepath = os.path.join(self.HISTORICAL_DIR, f"{incident_id}.log")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return filepath
        except Exception as e:
            log.error(f"Save failed: {e}")
            return ""

    def _embed_in_chromadb(self, incident_id: str, content: str, service: str) -> bool:
        try:
            from core.rag_engine import RAGEngine
            from core.llm_provider import provider

            rag = RAGEngine("logs/historical")

            # Chunk the content into lines for embedding
            lines = [l for l in content.splitlines() if l.strip()]
            chunks = ["\n".join(lines[i:i+20]) for i in range(0, len(lines), 20)]
            if not chunks:
                return False

            embeddings = provider.embed(chunks)

            ids = [f"{incident_id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [{
                "source_file": f"{incident_id}.log",
                "chunk_index": i,
                "incident_type": "auto-saved",
                "resolution": "",
                "severity": "",
                "date": "",
                "service": service,
                "auto_saved": "true"
            } for i in range(len(chunks))]

            rag.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas
            )
            return True
        except Exception as e:
            log.warn(f"Embedding failed: {e}")
            return False