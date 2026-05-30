"""tree-sitter AST seed extraction parity and precision for the dependency scanner."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import cross_service_dependency_scan as scan_mod

HAS_TS = (
    importlib.util.find_spec("tree_sitter") is not None
    and importlib.util.find_spec("tree_sitter_java") is not None
)
requires_ts = pytest.mark.skipif(not HAS_TS, reason="tree-sitter Java not installed")


def make_repo(tmp_path: Path) -> Path:
    orders = tmp_path / "services" / "orders" / "src" / "main" / "java" / "demo"
    billing = tmp_path / "services" / "billing" / "src" / "main" / "java" / "demo"
    orders.mkdir(parents=True)
    billing.mkdir(parents=True)
    (orders / "OrderController.java").write_text(
        "package demo;\n"
        "@RequestMapping(\"/api\")\n"
        "class OrderController {\n"
        "    @GetMapping(\"/orders\")\n"
        "    String list() { return \"\"; }\n"
        "}\n",
        encoding="utf-8",
    )
    (orders / "Topics.java").write_text(
        "package demo;\n"
        "class Topics {\n"
        "    public static final String ORDER_CREATED = \"order.created\";\n"
        "}\n",
        encoding="utf-8",
    )
    (orders / "OrderPublisher.java").write_text(
        "package demo;\n"
        "class OrderPublisher {\n"
        "    void emit() { dmqTemplate.send(Topics.ORDER_CREATED, \"tagA\"); }\n"
        "}\n",
        encoding="utf-8",
    )
    (billing / "BillingListener.java").write_text(
        "package demo;\n"
        "class BillingListener {\n"
        "    @DmqListener(topic = Topics.ORDER_CREATED)\n"
        "    void onOrder() {}\n"
        "}\n",
        encoding="utf-8",
    )
    (billing / "BillingClient.java").write_text(
        "package demo;\n"
        "class BillingClient {\n"
        "    @Value(\"${orders.base-url}\")\n"
        "    private String ordersUrl;\n"
        "}\n",
        encoding="utf-8",
    )
    return tmp_path


@requires_ts
def test_backend_reports_ast_active_when_available():
    backend = scan_mod.java_parser_backend()
    assert backend["tree_sitter_available"] is True
    assert backend["ast_parser_active"] is True
    assert backend["backend"] == "tree-sitter"
    # No self-deprecating "installed but not wired" warning when AST is active.
    assert not backend.get("warning")


@requires_ts
def test_routes_ast_matches_regex(tmp_path):
    repo = make_repo(tmp_path)
    services = scan_mod.detect_services(repo)
    regex_routes = scan_mod.extract_routes(repo, services, ast=False)
    ast_routes = scan_mod.extract_routes(repo, services, ast=True)
    norm = lambda rs: sorted((r["service"], r["method"], r["path"]) for r in rs)
    assert norm(ast_routes) == norm(regex_routes)
    assert ("services/orders", "GET", "/api/orders") in norm(ast_routes)


@requires_ts
def test_value_refs_ast_matches_regex(tmp_path):
    text = (
        "class C {\n"
        "    @Value(\"${orders.base-url:http://x}\")\n"
        "    private String ordersUrl;\n"
        "}\n"
    )
    assert scan_mod.variable_config_refs(text, ast=True) == scan_mod.variable_config_refs(text, ast=False)
    assert scan_mod.variable_config_refs(text, ast=True) == {"ordersUrl": "orders.base-url"}


@requires_ts
def test_messaging_ast_matches_regex(tmp_path):
    repo = make_repo(tmp_path)
    services = scan_mod.detect_services(repo)
    p_regex, c_regex = scan_mod.extract_messaging(repo, services, ast=False)
    p_ast, c_ast = scan_mod.extract_messaging(repo, services, ast=True)
    topics = lambda items: sorted((i["service"], i["topic"]) for i in items)
    assert topics(p_ast) == topics(p_regex)
    assert topics(c_ast) == topics(c_regex)
    assert ("services/orders", "order.created") in topics(p_ast)
    assert ("services/billing", "order.created") in topics(c_ast)


@requires_ts
def test_ast_ignores_commented_annotation(tmp_path):
    # regex matches an annotation inside a comment (false positive); AST does not.
    service_dir = tmp_path / "services" / "orders" / "src" / "main" / "java"
    service_dir.mkdir(parents=True)
    (service_dir / "Ghost.java").write_text(
        "package demo;\n"
        "class Ghost {\n"
        "    // @PostMapping(\"/ghost\")\n"
        "    @GetMapping(\"/real\")\n"
        "    String real() { return \"\"; }\n"
        "}\n",
        encoding="utf-8",
    )
    services = scan_mod.detect_services(tmp_path)
    regex_paths = {r["path"] for r in scan_mod.extract_routes(tmp_path, services, ast=False)}
    ast_paths = {r["path"] for r in scan_mod.extract_routes(tmp_path, services, ast=True)}
    assert "/ghost" in regex_paths  # documents the regex false positive
    assert "/ghost" not in ast_paths
    assert "/real" in ast_paths


@requires_ts
def test_scan_uses_ast_backend_without_warning(tmp_path):
    repo = make_repo(tmp_path)
    result = scan_mod.scan(repo, gitnexus_mode="off", write_reports=False)
    assert result["java_parser"]["ast_parser_active"] is True
    assert not any("not wired" in w for w in result["warnings"])


@requires_ts
def test_require_tree_sitter_ast_passes_when_available(tmp_path):
    repo = make_repo(tmp_path)
    result = scan_mod.scan(repo, gitnexus_mode="off", write_reports=False, require_tree_sitter_ast=True)
    assert not any("AST parsing is required but not active" in r for r in result["blocked_reasons"])


def _force_no_tree_sitter(monkeypatch):
    monkeypatch.setattr(scan_mod, "_PARSER_CACHE", [])

    def _raise():
        raise ImportError("tree-sitter disabled for test")

    monkeypatch.setattr(scan_mod, "_ts_parser", _raise)


def test_backend_honest_when_tree_sitter_absent(monkeypatch):
    _force_no_tree_sitter(monkeypatch)
    backend = scan_mod.java_parser_backend()
    assert backend["backend"] == "regex-fallback"
    assert backend["ast_parser_active"] is False
    assert "unavailable" in backend["warning"]


def test_scan_regex_fallback_still_ready_and_require_blocks(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    _force_no_tree_sitter(monkeypatch)
    ok = scan_mod.scan(repo, gitnexus_mode="off", write_reports=False)
    assert ok["java_parser"]["ast_parser_active"] is False
    assert ok["ready"]  # regex fallback still produces a usable report
    # AST-required policy must block when only regex is available
    blocked = scan_mod.scan(repo, gitnexus_mode="off", write_reports=False, require_tree_sitter_ast=True)
    assert not blocked["ready"]
    assert any("not active" in r for r in blocked["blocked_reasons"])
