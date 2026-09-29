"""A dashboard's chart config carries what the chart was drawn on.

Analytics grew multi-series, stacked bars, scatter, histogram, heatmap and KPI tiles.
ChartConfig silently dropped every field it did not declare, so a dashboard saved from
those charts came back as a single-measure chart. These tests pin that the new fields
survive, that a config from before them is still valid, and that the assistant's
dashboard.save action can carry the axes too — without changing what a caller that
sends only `chart_type` gets.
"""
import pytest
from pydantic import ValidationError

from app.chat.analysis import dashboards
from app.schemas.dashboard import ChartConfig


def test_new_fields_survive_a_round_trip():
    cfg = ChartConfig(chartType="bar", xAxis="day", yAxes=["a", "b"], stacked=True,
                      aggregate="avg", horizontal=False, colorBy="region")
    dumped = cfg.model_dump()
    assert dumped["yAxes"] == ["a", "b"]
    assert dumped["stacked"] is True
    assert dumped["aggregate"] == "avg"
    assert dumped["horizontal"] is False
    assert dumped["colorBy"] == "region"


def test_a_config_from_before_multi_series_is_still_valid():
    cfg = ChartConfig(chartType="bar", xAxis="region", yAxis="revenue")
    dumped = cfg.model_dump()
    assert dumped["yAxis"] == "revenue"
    assert dumped["yAxes"] is None


@pytest.mark.parametrize("kind", ["table", "line", "bar", "area", "pie",
                                  "kpi", "scatter", "histogram", "heatmap"])
def test_every_chart_type_is_accepted(kind):
    assert ChartConfig(chartType=kind).chartType == kind


def test_grid_and_legend_choices_are_kept():
    dumped = ChartConfig(chartType="line", showGrid=False, showLegend=False).model_dump()
    assert dumped["showGrid"] is False and dumped["showLegend"] is False


def test_more_than_five_measures_are_refused():
    with pytest.raises(ValidationError):
        ChartConfig(chartType="line", yAxes=list("abcdef"))


def test_an_unknown_aggregation_is_refused():
    with pytest.raises(ValidationError):
        ChartConfig(chartType="bar", aggregate="median")


def test_assistant_save_with_only_chart_type_keeps_the_old_shape():
    params = dashboards.DashboardSave(name="d", sql="SELECT 1", chart_type="bar").model_dump()
    body = dashboards.build_dashboard_create(params)
    assert body.chart_config.chartType == "bar"
    assert body.chart_config.xAxis is None
    assert body.chart_config.yAxes is None


def test_assistant_save_defaults_to_a_table():
    params = dashboards.DashboardSave(name="d", sql="SELECT 1").model_dump()
    assert dashboards.build_dashboard_create(params).chart_config.chartType == "table"


def test_assistant_save_carries_the_axes_into_the_chart_config():
    params = dashboards.DashboardSave(
        name="d", sql="SELECT 1", chart_type="bar", x_axis="day", y_axes=["a", "b"],
        color_by=None, aggregate="sum", stacked=True,
    ).model_dump()
    cfg = dashboards.build_dashboard_create(params).chart_config
    assert cfg.xAxis == "day"
    assert cfg.yAxes == ["a", "b"]
    assert cfg.yAxis == "a", "yAxis stays the first measure for readers of the older field"
    assert cfg.stacked is True
    assert cfg.aggregate == "sum"


def test_assistant_save_rejects_fields_it_does_not_declare():
    with pytest.raises(ValidationError):
        dashboards.DashboardSave(name="d", sql="SELECT 1", surprise=1)
