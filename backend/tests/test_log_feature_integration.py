from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_admin_registers_analysis_and_batch_export_routes():
    from app.admin_main import app

    paths = {route.path for route in app.routes}
    assert "/api/admin/log-analysis/summary" in paths
    assert "/api/admin/log-exports" in paths


def test_fresh_install_contains_analysis_and_batch_export_tables():
    init_sql = (REPO_ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS sdk_log_decodes" in init_sql
    assert "CREATE TABLE IF NOT EXISTS sdk_log_export_jobs" in init_sql


def test_log_viewer_keeps_analysis_views_and_batch_export_panel():
    source = (REPO_ROOT / "frontend" / "src" / "views" / "LogViewer.vue").read_text(
        encoding="utf-8"
    )

    assert 'data-testid="analysis-view-tab"' in source
    assert 'data-testid="raw-view-tab"' in source
    assert "<LogExportPanel" in source
