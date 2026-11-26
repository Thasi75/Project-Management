import os
import tempfile
from pathlib import Path
import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix='pm-tests-'))
os.environ['PM_DATA_DIR'] = str(TEST_DIR)

from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture(scope='session')
def client():
    with TestClient(app, headers={'X-PM-Client': 'workbench'}) as instance:
        yield instance


@pytest.fixture
def setup_project(client):
    def create(name='验收项目'):
        p = client.post('/api/projects', json={'name': name, 'scope': '实施订单、库存和交付培训',
            'effective_date': '2026-10-01'}).json()
        person = client.post('/api/projects/' + p['id'] + '/people', json={'name': name + '负责人'}).json()
        response = client.put('/api/projects/' + p['id'], json={'name': name, 'scope': p['scope'],
            'owner_id': person['id'], 'version': p['version'], 'effective_date': '2026-10-01', 'reason': '指定项目负责人'})
        assert response.status_code == 200, response.text
        p = response.json()
        module = client.get('/api/projects/' + p['id'] + '/modules').json()[0]
        return p, person, module
    return create


def create_record(client, project, kind, data, key=None):
    import uuid
    return client.post(f'/api/projects/{project["id"]}/records/{kind}', json=data,
                       headers={'Idempotency-Key': key or uuid.uuid4().hex})


def task_data(person, **changes):
    return {'name': '订单上线', 'owner_id': person['id'], 'plan_start': '2026-11-01', 'plan_end': '2026-11-07',
            'planned_deliverable': '验收清单', 'effective_date': '2026-11-01', **changes}
