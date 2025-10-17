from bokeh.models import ColumnDataSource, HoverTool, BoxAnnotation
from bokeh.plotting import figure, show
from bokeh.transform import factor_cmap, factor_hatch, cumsum
from bokeh.core.enums import HatchPattern
import pandas as pd
import numpy as np
from iso_week_date.pandas_utils import datetime_to_isoweek, isoweek_to_datetime
from dateutil import rrule



def read_data():
    # TODO: switch to reading from stdin
    df = pd.read_csv("data/example_data.csv", names=["timestamp", "yAxis", "nodeSize", "pieGroupId", "sliceGroupId"])
    return df


def _compute_timestamp_fields(df):
    df.timestamp = pd.to_datetime(df.timestamp)
    df["timestamp_isoweek"] = datetime_to_isoweek(series=df.timestamp)
    df["timestamp_month"] = df.timestamp.dt.strftime("%Y-%m")
    df["timestamp_day"] = df.timestamp.dt.strftime("%Y-%m-%d")

    # TODO: Make this dependent on CLI option
    # Choose weekday 4 (Thursday) to get a center coordinate for the week/pie chart
    df.timestamp = isoweek_to_datetime(series=df.timestamp_isoweek, weekday=4) + pd.to_timedelta(12, unit="h")

    return df


def _compute_week_bands(df):
    time_span = pd.Series(
                    rrule.rrule(
                        rrule.WEEKLY,
                        dtstart=df.timestamp.min(),
                        until=df.timestamp.max() + pd.to_timedelta(1, unit="w")
                    )
                )
    iso_weeks_span = datetime_to_isoweek(series=time_span)
    week_band_dates = zip(
        isoweek_to_datetime(series=iso_weeks_span, weekday=1),
        isoweek_to_datetime(series=iso_weeks_span, weekday=7)  # + pd.to_timedelta(1, unit="d")
    )
    week_band_dates = list(week_band_dates)[::2]
    return week_band_dates


def _compute_piechart_radii(week_band_dates):
    week_start_dt, week_end_dt = week_band_dates[0]
    week_start_dt_ns = week_start_dt.to_datetime64().astype(int)
    week_end_dt_ns = week_end_dt.to_datetime64().astype(int)
    week_len_in_ns = week_end_dt_ns - week_start_dt_ns
    max_radius = week_len_in_ns // 2

    min_radius = pd.to_timedelta(36, unit="h").to_timedelta64().astype(int)

    return min_radius, max_radius


def _collect_scatterplot_data(df, min_radius, max_radius):
    df_scatter = df.groupby(["timestamp", "pieGroupId"])[["yAxis","nodeSize"]].sum().reset_index()

    df_scatter["nodeRadius"] = np.interp(
        df_scatter.nodeSize,
        [df_scatter.nodeSize.min(), df_scatter.nodeSize.max()],
        [min_radius, max_radius]
    ).astype(int)
    df_scatter["nodeRadius"] = pd.to_timedelta(df_scatter["nodeRadius"], unit="ns")
    # df_scatter["nodeRadius"] = df_scatter["nodeRadius"] // 10 **6
    return df_scatter


def _collect_piechart_data(df, df_scatter):
    df_pie_charts = df.groupby(["timestamp", "pieGroupId", "sliceGroupId"])[["yAxis","nodeSize"]].sum().reset_index()
    df_pie_charts = pd.merge(df_pie_charts, df_scatter, how="left", on=["timestamp", "pieGroupId"], suffixes=("_share", ""))
    df_pie_charts["angle"] = df_pie_charts["nodeSize_share"] / df_pie_charts["nodeSize"] * (2 * np.pi)

    starts = []
    ends = []
    pie_chart_groups = df_pie_charts.groupby(["timestamp", "pieGroupId"])
    for _, df_group in pie_chart_groups:
        starts.append(np.cumsum(np.insert(df_group.angle.values[:-1], 0, 0)))
        ends.append(np.cumsum(df_group.angle.values))
    df_pie_charts["start_angles"] = np.concatenate(starts, axis=0)
    df_pie_charts["end_angles"] = np.concatenate(ends, axis=0)

    return df_pie_charts


def _collect_group_box_data(df, df_scatter):
    df_boxes = df.groupby(["timestamp", "pieGroupId"])[["yAxis","nodeSize"]].sum().reset_index()
    # TODO: continue here!


def preprocess_data(df):
    _compute_timestamp_fields(df)
    week_band_dates  =_compute_week_bands(df)

    min_radius, max_radius = _compute_piechart_radii(week_band_dates)
    df_scatter = _collect_scatterplot_data(df, min_radius, max_radius)
    df_pie_charts = _collect_piechart_data(df, df_scatter)

    return week_band_dates, df_scatter, df_pie_charts


def create_plot(week_band_dates, df_scatter, df_pie_charts, title="Default"):

    color_map = factor_cmap(
        "pieGroupId", palette="Category20_20",  # "Colorblind8"
        factors=df_scatter.pieGroupId.unique()
    )
    hatch_pattern_map = factor_hatch(
        "sliceGroupId",
        patterns=['dot',
 'ring',
 'vertical_line',
 'cross',
 'horizontal_dash',
 'vertical_dash',
 'spiral',
 'right_diagonal_line',
 'left_diagonal_line',
 'diagonal_cross',
 'right_diagonal_dash',
 'left_diagonal_dash',
 'horizontal_wave',
 'vertical_wave',
 'criss_cross'],
        factors=df_pie_charts.sliceGroupId.unique()
    )

    p = figure(
        width=1900, height=800,
        title=title,
        toolbar_location=None,
        # y_axis_type="log",
        x_axis_type="datetime",
        y_range=(0, df_pie_charts.yAxis.max() + 2)
    )

    # Create gray background bands
    boxes = [
        BoxAnnotation(
            fill_color="#bbbbbb",
            fill_alpha=0.1,
            left=week_start,
            right=week_end+pd.to_timedelta(1, unit="d"),
            # https://github.com/bokeh/bokeh/issues/13980#issuecomment-2226960920
            propagate_hover=True
        )
        for week_start, week_end in week_band_dates
    ]
    p.renderers.extend(boxes)

    source = ColumnDataSource(data=df_scatter)
    # for pieGroupId in df_scatter.pieGroupId.unique():
    #     # This loop is necessary to set the legend labels for the interactive
    #     # legend. It cannot be done shorter with argument `legend_group="pieGroupId"`, see
    #     # https://docs.bokeh.org/en/latest/docs/user_guide/basic/annotations.html#interactive-legends
    #     small_source = ColumnDataSource(data=df_scatter[df_scatter.pieGroupId == pieGroupId])
    #     p.scatter("timestamp", "yAxis", size="nodeRadius", fill_color=None,
    #                 line_width=4, line_color=cmap, legend_label=pieGroupId,
                    # source=small_source)

    # for pieGroupId in df_scatter.pieGroupId.unique():
    #     # This loop is necessary to set the legend labels for the interactive
    #     # legend. It cannot be done shorter with argument `legend_group="pieGroupId"`, see
    #     # https://docs.bokeh.org/en/latest/docs/user_guide/basic/annotations.html#interactive-legends
    #     small_source = ColumnDataSource(data=df_scatter[df_scatter.pieGroupId == pieGroupId])
    #     p.circle(
    #         "timestamp",
    #         "yAxis",
    #         radius=pd.to_timedelta(2, unit="d"),
    #         fill_color=None,
    #         line_width=6,
    #         line_color=color_map,
    #         legend_label=pieGroupId,
    #         source=small_source
    #     )

# https://codereview.stackexchange.com/questions/202416/plot-random-generated-n-non-colliding-circles-using-matplotlib
# https://github.com/mhtchan/packcircles
# https://github.com/xnx/circle-packing
# https://www.nodebox.net/code/index.php/shared_2008-08-07-12-55-33


    # p.block(
    #     x="",
    #     y="",
    #     width="w",
    #     height="h",
    #     fill_alpha=1.0,
    #     fill_color='gray',
    #     line_color='black',
    #     line_dash=[],
    #     line_dash_offset=0,
    #     line_join='bevel',
    #     line_width=1,
    # )

    circles = p.circle(
        x="timestamp",
        y="yAxis",
        radius="nodeRadius",
        fill_color=None,
        line_width=6,
        line_color=color_map,
        legend_group="pieGroupId",
        source=source
    )

    pie_data_source = ColumnDataSource(data=df_pie_charts)
    p.annular_wedge(
        x="timestamp",
        y="yAxis",
        inner_radius=pd.to_timedelta(18, unit="h"),
        outer_radius="nodeRadius",  # pd.to_timedelta(2, unit="d"), #"nodeSize",
        start_angle="start_angles",
        end_angle="end_angles",
        line_color="black",
        fill_color=None,
        hatch_pattern=hatch_pattern_map,
        hatch_color="black",
        hatch_scale=5,
        alpha=0.6,
        legend_field="sliceGroupId",
        source=pie_data_source,
    )

    p.add_tools(HoverTool(
        tooltips=[
            # TODO: Set proper name and style it
            ("Node", "@pieGroupId"),
            ("Timestamp", "@timestamp{%F}"),
            ("Commit", "@yAxis"),
            ("Churn", "@nodeSize")
        ],
        formatters={
            "@timestamp": "datetime",
        },
        # https://discourse.bokeh.org/t/use-hovertool-for-some-glyphs-but-not-others-in-a-plot/10749/2
        renderers=[circles]
    ))

    # I would like to have a highlight option, but it does not seem to exist yet
    # https://github.com/bokeh/bokeh/issues/8841
    p.legend.click_policy="mute"

    # https://stackoverflow.com/a/62159166
    # https://docs.bokeh.org/en/latest/docs/examples/styling/plots/legend_location_outside.html
    p.add_layout(p.legend[0], 'right')

    return p


# for row in df.itertuples(index=False):
#     print("------------")
#     print(row)
#     print(row.timestamp, row.pieGroupId)
#     print(df_scatter[(df_scatter.timestamp == row.timestamp) & (df_scatter.pieGroupId == row.pieGroupId)][["yAxis","nodeSize"]])

# pie_chart_groups = df.groupby(["timestamp", "pieGroupId", "sliceGroupId"])
# for (timestamp, pieGroupId, _), df_group in pie_chart_groups:
#     print("------------")
#     print(df_scatter[(df_scatter.timestamp == timestamp) & (df_scatter.pieGroupId == pieGroupId)][["yAxis","nodeSize"]].sum())
#     print(df_group.timestamp)
#     print(df_group.sliceGroupId.unique()[0])
#     print(df_group[["yAxis","nodeSize"]].sum())


def create_repopie_plot(title="Default title"):
    df = read_data()
    week_band_dates, df_scatter, df_pie_charts = preprocess_data(df)

    df_pie_charts.to_csv("pie_charts.csv", index=False)

    p = create_plot(week_band_dates, df_scatter, df_pie_charts, title=title)
    return p


def main():
    p = create_repopie_plot()
    show(p)

