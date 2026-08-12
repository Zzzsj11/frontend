from __future__ import annotations

import uuid


def _run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_request_logged_with_run_header(client):
    run_id = _run_id("logged")
    response = client.get("/api/auth/me", headers={"X-Test-Run-Id": run_id})
    assert response.status_code == 200
    logs = client.get("/api/admin/request-logs", params={"runId": run_id}).json()
    assert logs["total"] == 1
    item = logs["items"][0]
    assert item["path"] == "/api/auth/me"
    assert item["method"] == "GET"
    assert item["statusCode"] == 200
    assert item["durationMs"] >= 0
    detail = client.get(f"/api/admin/request-logs/{item['id']}").json()
    assert detail["responseBody"]["username"] == "admin"


def test_not_logged_without_run_header(client):
    saved = client.headers.pop("X-Test-Run-Id")
    try:
        before = client.get("/api/admin/request-logs", params={"limit": 1}).json()["total"]
        assert client.get("/api/auth/me").status_code == 200
        after = client.get("/api/admin/request-logs", params={"limit": 1}).json()["total"]
        assert after == before
    finally:
        client.headers["X-Test-Run-Id"] = saved


def test_password_redacted_in_request_payload(client):
    run_id = _run_id("redact")
    client.post("/api/auth/login", json={"username": "admin", "password": "123456"}, headers={"X-Test-Run-Id": run_id})
    logs = client.get("/api/admin/request-logs", params={"runId": run_id}).json()
    assert logs["total"] == 1
    detail = client.get(f"/api/admin/request-logs/{logs['items'][0]['id']}").json()
    assert detail["requestPayload"]["username"] == "admin"
    assert detail["requestPayload"]["password"] == "***"
    # 登录成功响应中的 camelCase 令牌键同样必须脱敏，避免可用令牌落库
    assert detail["responseBody"]["accessToken"] == "***"


def test_polling_requests_skipped(client):
    """轮询/长连接请求（X-Polling: 1）不落库：每 2-5 秒刷一次或挂几分钟，
    全量记录会刷出海量重复数据并污染慢请求统计（SSE 的 duration_ms 等于连接时长）。"""
    run_id = _run_id("polling")
    saved = client.headers.pop("X-Test-Run-Id")
    client.headers["X-Test-Run-Id"] = run_id
    try:
        # 普通请求落库
        assert client.get("/api/auth/me").status_code == 200
        # 同一路径带轮询标记不落库
        assert (
            client.get(
                "/api/auth/me",
                headers={"X-Polling": "1"},
            ).status_code
            == 200
        )
    finally:
        client.headers["X-Test-Run-Id"] = saved
    logs = client.get("/api/admin/request-logs", params={"runId": run_id}).json()
    assert logs["total"] == 1
    assert logs["items"][0]["path"] == "/api/auth/me"


def test_request_logs_filter_min_ms_and_sort_by_duration(client):
    """慢请求 TOP：minMs 只返回耗时达标的请求，orderBy=duration 按耗时倒序。"""
    run_id = _run_id("slow")
    for _ in range(3):
        client.get("/api/auth/me", headers={"X-Test-Run-Id": run_id})
    # minMs 过滤（阈值取 1ms：正常请求都能通过，验证参数链路）
    filtered = client.get(
        "/api/admin/request-logs", params={"runId": run_id, "minMs": 1}
    ).json()
    assert filtered["total"] == 3
    # 荒谬大阈值 → 一条都没有（说明条件真实生效）
    none = client.get(
        "/api/admin/request-logs", params={"runId": run_id, "minMs": 10**9}
    ).json()
    assert none["total"] == 0
    # orderBy=duration：耗时倒序返回
    by_duration = client.get(
        "/api/admin/request-logs", params={"runId": run_id, "orderBy": "duration"}
    ).json()
    durations = [item["durationMs"] for item in by_duration["items"]]
    assert durations == sorted(durations, reverse=True)


def test_request_log_summary_aggregates_by_path(client):
    """聚合接口：正式流量按 path+method 汇总 count/avg/p95/max。

    测试客户端默认带 X-Test-Run-Id，summary 只统计正式流量（run_id 为空），
    因此本批次请求不应出现在聚合结果里——验证隔离逻辑。
    """
    run_id = _run_id("summary")
    client.get("/api/auth/me", headers={"X-Test-Run-Id": run_id})
    summary = client.get(
        "/api/admin/request-logs/summary", params={"hours": 24, "minCount": 1}
    ).json()
    assert isinstance(summary, list)
    assert all(
        row["count"] >= 1 and row["avgMs"] >= 0 and row["p95Ms"] >= 0 and row["maxMs"] >= 0
        for row in summary
    )
    assert not any(row["path"] == "/api/auth/me" for row in summary)


def test_runs_aggregation(client):
    run_id = _run_id("runs")
    for _ in range(3):
        assert client.get("/api/auth/me", headers={"X-Test-Run-Id": run_id}).status_code == 200
    runs = client.get("/api/admin/request-logs/runs").json()
    mine = next((row for row in runs if row["runId"] == run_id), None)
    assert mine is not None
    assert mine["requests"] >= 3
    assert mine["maxMs"] >= mine["avgMs"] >= 0
    assert mine["errors"] == 0


def test_filters_by_path_and_status(client):
    run_id = _run_id("filter")
    client.get("/api/auth/me", headers={"X-Test-Run-Id": run_id})
    client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}, headers={"X-Test-Run-Id": run_id})
    by_path = client.get("/api/admin/request-logs", params={"runId": run_id, "path": "login"}).json()
    assert by_path["total"] == 1
    # 登录失败的状态码因环境而异（本地 422 / 线上 401），此处只关注留痕与筛选
    assert 400 <= by_path["items"][0]["statusCode"] < 500
    by_status = client.get("/api/admin/request-logs", params={"runId": run_id, "status": 200}).json()
    assert by_status["total"] == 1
    assert by_status["items"][0]["path"] == "/api/auth/me"


def test_request_logs_require_admin(client):
    saved_auth = client.headers.pop("Authorization")
    try:
        assert client.get("/api/admin/request-logs").status_code == 401
        assert client.get("/api/admin/request-logs/runs").status_code == 401
    finally:
        client.headers["Authorization"] = saved_auth
