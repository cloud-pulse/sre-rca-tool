# Chapter 3: Literature Survey

This chapter surveys research that motivates the design of the proposed AI-assisted Root Cause Analysis (RCA) framework for cloud-native microservices. The literature is organized around four themes that directly map to the implemented pipeline in this project: (i) log-based anomaly detection, (ii) microservice-oriented failure diagnosis, (iii) Retrieval-Augmented Generation (RAG) for leveraging historical evidence, and (iv) AI-enabled operations (AIOps) practices. The chapter closes with the identified gap that our framework addresses.

## 3.1 Log-Based Anomaly Detection

Cloud-native systems generate extremely large volumes of operational data, particularly unstructured application and infrastructure logs. A core prerequisite for effective RCA is therefore detecting abnormal behavior within log streams.

Early work on log anomaly detection treats logs as ordered sequences and learns statistical/representational structure. Zhang et al. introduced **DeepLog**, a deep learning approach based on LSTM models for log sequence anomaly detection. Their method models the semantics of log sequences and detects deviations from expected patterns, demonstrating strong empirical performance on large-scale datasets (e.g., HDFS logs).

While DeepLog shows that deep models can learn useful representations from log sequences, its assumptions commonly focus on a single log source and on purely anomaly detection rather than causal diagnosis. In practice, microservice incidents rarely originate from one component; rather, they propagate through dependent services and infrastructure layers. Furthermore, logs alone often do not provide enough context for “why” an incident occurred (e.g., whether an observed symptom is a primary cause or a downstream effect). These limitations motivate our design choice to combine **pre-LLM pattern detection** and **service-aware dependency reasoning**, rather than relying purely on anomaly detection.

## 3.2 Failure Diagnosis in Microservices

Microservice architectures introduce complex dependency graphs: one service failure can cascade into failures in upstream and downstream services. RCA in this setting therefore requires not only evidence extraction, but also correlation across components.

Chen et al. proposed **MicroRCA**, a microservice failure diagnosis approach using invariant mining. MicroRCA focuses on discovering invariants from service metrics and traces (as available) to localize root causes for microservice anomalies. The approach is effective at identifying dependency-related failures when sufficient supervised or structured signals are available.

However, microservice diagnosis methods like MicroRCA may not fully address scenarios dominated by unstructured logs or environments where labeled datasets are unavailable. In many operational settings, SRE teams must work with heterogeneous evidence sources such as container logs, event histories, and proxy logs. These observations motivate a log-centric RCA pipeline enhanced with dependency information (e.g., blast radius) and historical retrieval.

In this project, dependency relationships are derived from `services.yaml` and complemented by evidence-based service resolution. Additionally, rule-based detectors capture high-precision failure triggers (e.g., **OOMKilled**, connection timeouts, crash loops) before passing richer context to the LLM. This design reflects the key principle suggested by microservice diagnosis literature: diagnosis accuracy improves when causal inference is made explicitly aware of system structure.

## 3.3 Retrieval-Augmented Generation (RAG) for Evidence Reuse

Large Language Models (LLMs) can provide flexible reasoning and structured explanations, but they may still underperform when the incident domain requires precise knowledge or consistent formatting across repeated failure types. **RAG** addresses this limitation by retrieving relevant external context and conditioning the LLM on it.

Lewis et al. demonstrated that RAG improves performance in knowledge-intensive tasks by retrieving and integrating relevant documents, outperforming purely parametric memory. The central idea—retrieving similar past information and grounding the model’s response—maps naturally to SRE RCA. For recurring incident categories, historical RCA notes and incident logs contain the “missing” factual context that an LLM would otherwise infer less reliably.

In our framework, RAG is implemented using a vector database and embedding model to match the current incident’s evidence against a repository of historical incidents. Retrieved contexts are then injected into the LLM prompt to support higher-confidence causal ranking and remediation generation.

### 3.3.1 RAG vs. Baseline Prompting in RCA

Without retrieval, an LLM must rely solely on general knowledge and on the raw incident evidence provided in the prompt. In practice, incident narratives often contain subtle trigger lines and operational constraints that are best matched to prior cases. Therefore, RAG is expected to:

- Improve causal specificity (reducing generic explanations).
- Increase confidence calibration for repeated failure modes.
- Encourage consistent remediation patterns aligned with prior incidents.

This project’s evaluation pipeline explicitly compares a baseline LLM mode and a RAG-augmented mode to quantify these effects.

## 3.4 AIOps and AI-Assisted Operations

AIOps applies ML and automation techniques to operational workflows such as monitoring, anomaly detection, and incident triage. Gartner’s industry forecasts suggest significant adoption growth of AIOps systems in enterprise environments, largely driven by the need to reduce MTTR and to automate repetitive analysis tasks.

However, many AIOps tools in industry are proprietary and operate as black boxes, limiting transparency and modifiability of diagnostic logic. Additionally, systems that only detect anomalies without producing actionable RCA outputs may still require extensive human interpretation.

Our project aligns with the direction of AI-assisted operations but adds a key differentiator: **editable, pipeline-based prompts and structured RCA outputs**, combined with retrieval from historical incidents and rule-based pre-processing. This combination provides both speed and interpretability.

## 3.5 Identified Research Gap

Across the above literature, several gaps remain relevant for practical SRE RCA:

1. **Single-source focus**: Many approaches emphasize either a single log stream or structured metrics/traces.
2. **Insufficient causal structure**: Microservice diagnosis often assumes explicit dependency signals and may not incorporate unstructured log narratives.
3. **Limited evidence grounding**: Baseline LLM prompting may lack consistent anchoring to prior incident resolutions.
4. **Lack of end-to-end automation**: Some methods diagnose, but do not integrate an operational loop that can persist newly learned incidents and improve over time.

This motivates the need for a unified framework that combines:

- Log cleaning and targeted pattern detection for high-signal triggers.
- Dependency-aware RCA to reason about blast radius.
- RAG over historical incidents to ground LLM reasoning.
- Auto-persistence of newly analyzed cases for continual learning.

## 3.6 Summary

This chapter surveyed foundational work in log anomaly detection, microservice failure diagnosis, RAG, and AIOps. The surveyed literature supports three core design choices implemented in this project: (i) pre-LLM filtering/detection to extract high-precision evidence, (ii) structured diagnosis guided by microservice dependency graphs, and (iii) retrieval grounding using historical incident evidence. Finally, the chapter identified the end-to-end evidence integration gap that our AI-assisted SRE RCA framework addresses.

`