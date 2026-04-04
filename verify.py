from core.incident_recorder import IncidentRecorder
recorder = IncidentRecorder()

fake_analysis = '''
Root cause: Database connection pool exhausted.
Service payment-service failed after database-service OOMKilled.
Circuit breaker opened on api-gateway.
CONFIDENCE: 85%
REASON: Full failure sequence visible in logs.
'''

result = recorder.check_and_save(fake_analysis, 'payment-service', ['line1', 'line2', 'line3'])
print('saved:', result['saved'])
print('incident_id:', result['incident_id'])
print('similarity_score:', result['similarity_score'])
print('reason:', result['reason'])
