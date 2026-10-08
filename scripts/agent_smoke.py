"""Quota-free Agent integration smoke; isolated memory, no tools or persistent writes.

Run: python -m scripts.agent_smoke
"""
from unittest.mock import patch
from uuid import uuid4


def run_smoke():
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.memory import MemorySaver
    from src.agent import graph, nodes
    from src.agent.api import routes
    from src.agent.memory import checkpoint
    from src.agent.config import agent_config
    from src.agent.api.auth import create_auth_token
    from src.ui.web_server import app
    from scripts.colab_startup import agent_routes_present

    memory = MemorySaver()
    # Build a real LangGraph with MockChatModel, never the configured paid provider.
    with patch.object(nodes, 'get_llm', side_effect=lambda: nodes.MockChatModel()), \
         patch.object(checkpoint, '_checkpointer_instance', memory), \
         patch.object(graph, '_compiled_graph', None), \
         patch.object(agent_config, 'database_url', None):
        client = TestClient(app)
        identity = 'agent_smoke_' + uuid4().hex
        client.headers['Authorization'] = 'Bearer ' + create_auth_token(identity)
        assert agent_routes_present(client.get('/openapi.json').json())
        thread = 'smoke_' + uuid4().hex
        path = '/api/agent/conversations/' + thread
        empty = client.get(path)
        assert empty.status_code == 200 and empty.json()['messages'] == []
        for _ in range(2):
            chat = client.post('/api/agent/chat', json={'message': 'Hello', 'thread_id': thread})
            assert chat.status_code == 200
            assert chat.json()['status'] == 'success' and chat.json()['reply']
            assert chat.json()['tools_called'] == []
        history = client.get(path)
        assert history.status_code == 200 and history.json()['message_count'] == 4
        assert [m['type'] for m in history.json()['messages']] == ['human', 'ai', 'human', 'ai']
        assert client.post('/api/agent/chat', json={'message': ''}).status_code == 422
        with patch.object(routes, 'run_agent_message', return_value={'status': 'llm_unavailable', 'reply': 'Unavailable'}):
            error = client.post('/api/agent/chat', json={'message': 'Hello', 'thread_id': thread})
            assert error.status_code == 200 and error.json()['status'] == 'llm_unavailable'
        created = client.post('/api/agent/chat', json={'message': 'Hello'})
        assert created.status_code == 200 and created.json()['status'] == 'success'
        new_thread = created.json()['thread_id']
        assert new_thread != thread
        assert client.get('/api/agent/conversations/' + new_thread).json()['message_count'] == 2
        assert client.delete(path).json()['cleared'] is True
        assert client.get(path).json()['messages'] == []
        assert client.get('/api/agent/conversations/' + new_thread).json()['message_count'] == 2
    return {'agent_mock_api': 'PASS', 'real_llm_calls': 0}


if __name__ == '__main__':
    import json
    print(json.dumps(run_smoke()))
