from app.chat import chat
from app.retrieval import RetrievalRequest


async def test_chat_endpoint_delegates_to_retrieval_pipeline(monkeypatch) -> None:
    captured = {}

    async def fake_search_documents(request, session):
        captured["request"] = request
        captured["session"] = session
        return "response"

    monkeypatch.setattr("app.chat.search_documents", fake_search_documents)

    session = object()
    request = RetrievalRequest(query="how to enroll")
    response = await chat(request, session)  # type: ignore[arg-type]

    assert response == "response"
    assert captured == {"request": request, "session": session}
