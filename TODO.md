# TODO

## AnalyseHandler kubectl-mode refactor
- [ ] Confirm kubectl RCA output schema from core/kubectl_rca_investigator.py (already inspected) and how AnalyseHandler should map it into _print_analysis_result.
- [ ] Refactor core/command_registry.py::AnalyseHandler: remove nested kubectl helpers.
- [ ] Add AnalyseHandler._handle_kubectl(service)
- [ ] Add AnalyseHandler._resolve_service(service_name, sg, namespace) -> (resolved, found)
- [ ] Delete AnalyseHandler nested _print_kubectl_result (remove entirely).
- [ ] Add AnalyseHandler._collect_kubectl_evidence(rca) -> evidence_text
- [ ] Add AnalyseHandler._build_kubectl_prompt(service, rca, evidence_text) with exact CONFIDENCE/REASON block.
- [ ] Add AnalyseHandler._print_kubectl_context(rca, resolved, namespace) and call it before _print_analysis_result.
- [ ] Ensure early exit with clean error panel when service not found.
- [ ] Ensure confidence extraction regex matches WindowAnalyzer: r"CONFIDENCE:\s*(\d+)%"
- [ ] Ensure result dict matches _print_analysis_result expectations (service/windows_used/confidence/analysis/low_confidence_warning/incident_record).
- [ ] Run quick sanity check by importing main/command_registry and invoking AnalyseHandler.handle path (no kubectl required in tests).

