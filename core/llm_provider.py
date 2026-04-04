import json
import time
from typing import List, Optional

import requests

import flags
from flags import (
        LLM_PROVIDER, NVIDIA_API_KEY, LLM_BASE_URL,
        LLM_REASONING_MODEL, LLM_REASONING_FALLBACK,
        LLM_EMBEDDING_MODEL, LLM_EMBEDDING_FALLBACK,
        OLLAMA_URL, OLLAMA_MODEL, LLM_TIMEOUT,
        LLM_MAX_TOKENS, EMBEDDING_MODEL,
    )


class LLMProvider:
    def __init__(self):
        provider = (LLM_PROVIDER or "ollama").strip().lower()
        self.provider = "nvidia" if provider == "nvidia" else "ollama"

        self.reasoning_model = LLM_REASONING_MODEL
        self.reasoning_fallback = LLM_REASONING_FALLBACK
        self.embedding_model = LLM_EMBEDDING_MODEL
        self.embedding_fallback = LLM_EMBEDDING_FALLBACK

        self._client = None
        self._embedding_model_local = None

        if self.provider == "nvidia":
            from openai import OpenAI

            self._client = OpenAI(
                base_url=LLM_BASE_URL,
                api_key=NVIDIA_API_KEY,
            )

    def _is_429(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True

        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None) == 429:
            return True

        return "429" in str(exc)

    def _generate_nvidia(
        self,
        prompt: str,
        system_prompt: Optional[str],
        stream: bool,
        model: str,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            top_p=0.7,
            max_tokens=flags.LLM_MAX_TOKENS,
            stream=stream,
        )

        if not stream:
            return (response.choices[0].message.content or "").strip()

        chunks: List[str] = []
        for chunk in response:
            token = ""
            if chunk.choices and chunk.choices[0].delta:
                token = chunk.choices[0].delta.content or ""
            if token:
                print(token, end="", flush=True)
                chunks.append(token)
        print()
        return "".join(chunks).strip()

    def _generate_ollama(self, prompt: str, stream: bool) -> str:
        for attempt in range(3):
            try:
                payload = {
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": stream,
                    "options": {
                        "temperature": 0.2,
                        "top_p": 0.9,
"num_predict": LLM_MAX_TOKENS,
"keep_alive": ("10m" if LLM_KEEP_ALIVE else "0"),
                    },
                }

                response = requests.post(
                    OLLAMA_URL,
                    json=payload,
                    stream=stream,
                    timeout=(10, flags.LLM_TIMEOUT),
                )

                if response.status_code == 200:
                    if not stream:
                        data = response.json()
                        return (data.get("response") or "").strip()

                    full_response = ""
                    for line in response.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode("utf-8")
                        try:
                            data = json.loads(line_str)
                            token = data.get("response", "")
                            if token:
                                print(token, end="", flush=True)
                                full_response += token
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
                    print()
                    return full_response

                print(f"ERROR: Ollama returned status {response.status_code}")
            except requests.ConnectionError:
                print("ERROR: Cannot connect to Ollama")
            except requests.Timeout:
                print(f"ERROR: Ollama request timed out after {LLM_TIMEOUT}s")
            except Exception as exc:
                print(f"ERROR: Failed to call Ollama: {exc}")

            if attempt < 2:
                print(f"Retrying in 5 seconds... (attempt {attempt + 2}/3)")
                time.sleep(5)

        return ""

    def generate(self, prompt: str, system_prompt: Optional[str] = None, stream: bool = False) -> str:
        if self.provider == "nvidia":
            try:
                return self._generate_nvidia(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    stream=stream,
                    model=self.reasoning_model,
                )
            except Exception as exc:
                if self._is_429(exc):
                    print("[INFO] Primary model busy, switching to fallback model...")
                    try:
                        return self._generate_nvidia(
                            prompt=prompt,
                            system_prompt=system_prompt,
                            stream=stream,
                            model=self.reasoning_fallback,
                        )
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            "NVIDIA generation failed after fallback. "
                            f"Tried models: {self.reasoning_model}, {self.reasoning_fallback}"
                        ) from fallback_exc
                raise

        merged_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
        return self._generate_ollama(merged_prompt, stream=stream)

    def _embed_nvidia(self, texts: List[str], model: str) -> List[List[float]]:
        response = self._client.embeddings.create(
            model=model,
            input=texts,
            encoding_format="float",
        )
        return [item.embedding for item in response.data]

    def _embed_ollama_local(self, texts: List[str]) -> List[List[float]]:
        if self._embedding_model_local is None:
            from sentence_transformers import SentenceTransformer

        self._embedding_model_local = SentenceTransformer(EMBEDDING_MODEL)

        vectors = self._embedding_model_local.encode(texts, convert_to_numpy=True)
        return [vector.tolist() for vector in vectors]

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self.provider == "nvidia":
            try:
                return self._embed_nvidia(texts, self.embedding_model)
            except Exception as exc:
                if self._is_429(exc):
                    print("[INFO] Embedding model busy, switching to fallback...")
                    try:
                        return self._embed_nvidia(texts, self.embedding_fallback)
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            "NVIDIA embedding failed after fallback. "
                            f"Tried models: {self.embedding_model}, {self.embedding_fallback}"
                        ) from fallback_exc
                raise

        return self._embed_ollama_local(texts)

    def __repr__(self):
        return (
            f"LLMProvider({self.provider} | "
            f"reasoning={self.reasoning_model} | "
            f"embedding={self.embedding_model})"
        )


provider = LLMProvider()
