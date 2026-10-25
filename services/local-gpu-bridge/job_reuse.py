"""Select persisted request attempts without re-running uncertain or active jobs."""


def latest_attempt(jobs, request_id, fingerprint):
    matches = [job for job in jobs.values() if job.get('request_id') == request_id]
    if any(job.get('fingerprint') != fingerprint for job in matches):
        raise ValueError('Request id already used with different parameters.')
    return max(matches, key=lambda job: (job.get('attempt', 1), job.get('created_at', 0), job['id']), default=None)


def attempt_fields(previous):
    return {'attempt': previous.get('attempt', 1) + 1, 'retry_of': previous['id']} if previous else {'attempt': 1}
