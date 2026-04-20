"""
RepoPie 🥧, a tool to visualize numerical and categorical data over time.

Usage:
repopie [--y=<yname>] [--r=<rname>] [--title=<title>] [--nodecategory=<cat1label>] [--slicecategory=<cat2label>]
repopie -h | --help
repopie --version

Options:
-h --help                    Show this screen.
--version                    Show version.
--y=<ylabel>                 Label for numerical data on y-axis [default: yValues].
--r=<rlabel>                 Label for numerical data used as pie radii [default: rValues].
--title=<title>              Title of the graph [default: Graph].
--nodecategory=<cat1label>   Label for categorical data plotted as nodes in scatter plot [default: Nodes]
--slicecategory=<cat2label>  Label for categorical data plotted as slices in pie chart nodes [default: Slices]

Examples:

$ cat data/example_data.csv | \
  repopie --y=Commits --r=Churn --title=$(pwd) --nodecategory=File --slicecategory=Authors
"""

import sys

import numpy as np
import pandas as pd
from bokeh.io import output_file
from bokeh.models import BoxAnnotation, ColumnDataSource, HoverTool
from bokeh.plotting import figure, show
from bokeh.transform import factor_cmap, factor_hatch
from dateutil import rrule
from iso_week_date.pandas_utils import datetime_to_isoweek, isoweek_to_datetime
from packcircles import pack
from docopt import docopt


def read_data():
    df = pd.read_csv(
        sys.stdin,
        names=["timestamp", "yAxis", "nodeSize", "pieGroupId", "sliceGroupId"],
    )
    return df


def _compute_timestamp_fields(df):
    df.timestamp = pd.to_datetime(df.timestamp)
    df["timestamp_isoweek"] = datetime_to_isoweek(series=df.timestamp)
    df["timestamp_month"] = df.timestamp.dt.strftime("%Y-%m")
    df["timestamp_day"] = df.timestamp.dt.strftime("%Y-%m-%d")

    # TODO: Make this dependent on CLI option
    # Choose weekday 4 (Thursday) to get a center coordinate for the week/pie chart
    df.timestamp = isoweek_to_datetime(
        series=df.timestamp_isoweek, weekday=4
    ) + pd.to_timedelta(12, unit="h")

    return df


def _compute_week_bands(df):
    time_span = pd.Series(
        rrule.rrule(
            rrule.WEEKLY,
            dtstart=df.timestamp.min(),
            until=df.timestamp.max() + pd.to_timedelta(1, unit="w"),
        )
    )
    iso_weeks_span = datetime_to_isoweek(series=time_span)
    week_band_dates = zip(
        isoweek_to_datetime(series=iso_weeks_span, weekday=1),
        isoweek_to_datetime(
            series=iso_weeks_span, weekday=7
        ),  # + pd.to_timedelta(1, unit="d")
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

    # Circle area: A = πr**2
    # -> r = np.sqrt(A/np.pi)

    return min_radius, max_radius


def _collect_scatterplot_data(df, min_radius, max_radius):
    df_scatter = (
        df.groupby(["timestamp", "pieGroupId"])[["yAxis", "nodeSize"]]
        .sum()
        .reset_index()
    )

    df_scatter["nodeRadius"] = np.interp(
        df_scatter.nodeSize,
        [df_scatter.nodeSize.min(), df_scatter.nodeSize.max()],
        [min_radius, max_radius],
    ).astype(int)
    df_scatter["nodeRadius"] = pd.to_timedelta(df_scatter["nodeRadius"], unit="ns")
    return df_scatter


def _collect_piechart_data(df, df_scatter):
    df_pie_charts = (
        df.groupby(["timestamp", "pieGroupId", "sliceGroupId"])[["yAxis", "nodeSize"]]
        .sum()
        .reset_index()
    )
    df_pie_charts = pd.merge(
        df_pie_charts,
        df_scatter,
        how="left",
        on=["timestamp", "pieGroupId"],
        suffixes=("_share", ""),
    )
    df_pie_charts["angle"] = (
        df_pie_charts["nodeSize_share"] / df_pie_charts["nodeSize"] * (2 * np.pi)
    )

    starts = []
    ends = []
    pie_chart_groups = df_pie_charts.groupby(["timestamp", "pieGroupId"])
    for _, df_group in pie_chart_groups:
        starts.append(np.cumsum(np.insert(df_group.angle.values[:-1], 0, 0)))
        ends.append(np.cumsum(df_group.angle.values))
    df_pie_charts["start_angles"] = np.concatenate(starts, axis=0)
    df_pie_charts["end_angles"] = np.concatenate(ends, axis=0)

    return df_pie_charts


def _collect_group_box_data(df_scatter):
    df_scatter_count = (
        df_scatter.groupby(["timestamp", "yAxis"]).size().reset_index(name="amount")
    )
    df_boxes = df_scatter_count[df_scatter_count.amount > 1][["timestamp", "yAxis"]]
    return df_boxes


def _compute_group_bounding_box(df_boxes):
    # Set timestamp to the beginning of the week, i.e., Monday 00:00:00
    # `ts.weekday()` returns 0 for Monday, 1 for Tuesday, etc.
    # Consequently, subtracting that many days sets lower bound of bounding box to Monday.
    df_boxes.timestamp = (
        df_boxes.timestamp
        - pd.to_timedelta(df_boxes.timestamp.dt.weekday, unit="d")
        - pd.to_timedelta(12, unit="h")
    )
    df_boxes.yAxis = df_boxes.yAxis - 0.5
    df_boxes["height"] = 1
    df_boxes["width"] = pd.to_timedelta(1, unit="w")
    return df_boxes


def _compute_nonoverlapping_coordinates_per_box(df_scatter, timestamp, yAxis):
    # Convert the radii to integers in seconds, since the packcircles implementation cannot handle very large integers
    # in nanoseconds
    row_indexer = (df_scatter.timestamp == timestamp) & (df_scatter.yAxis == yAxis)
    radii_in_seconds = (
        pd.to_timedelta(df_scatter[row_indexer].nodeRadius).astype(int) // 10**9
    )
    if df_scatter[row_indexer].nodeRadius.size < 3:
        # the algorithm in the packcircles package needs at least three circles to pack them. In this case, to satisfy
        # the algorithm, I add a tiny dummy circle, which will be removed later.
        radii_in_seconds = pd.concat(
            [radii_in_seconds, pd.Series(1)], ignore_index=True
        )
    # Call the actual circle packing algorithm
    circles = pack(radii_in_seconds.values)
    if df_scatter[row_indexer].nodeRadius.size < 3:
        # Remove the dummy circle again
        circles = list(circles)[:-1]
    packed_circle_coords_df = pd.DataFrame(circles, columns=["Δx", "Δy", "nodeRadius"])
    # Convert the newly computed centers of packed circles back to time deltas and small values for y-coordinates so
    # that they can be placed in the original coordinate system.
    packed_circle_coords_df.Δx = pd.to_timedelta(packed_circle_coords_df.Δx, unit="s")
    packed_circle_coords_df.Δy = (packed_circle_coords_df.Δy // 10**6) / 2
    # Apply the newly computed coordinates to the scatter plot dataframe.
    df_scatter.loc[row_indexer, "x"] = (
        df_scatter.loc[row_indexer, "x"] + packed_circle_coords_df.Δx.values
    )
    df_scatter.loc[row_indexer, "y"] = (
        df_scatter.loc[row_indexer, "y"] + packed_circle_coords_df.Δy.values
    )
    return df_scatter


def _compute_nonoverlapping_coordinates(df_scatter):
    df_scatter["x"] = df_scatter["timestamp"]
    df_scatter["y"] = df_scatter["yAxis"].astype(float)
    # The following DataFrame holds the number of circles that would be plotted on the same x-/y-coordinates if only
    # timestamp (x-coordinate) and yAxis (y-coordinate) are considered.
    df_scatter_count = (
        df_scatter.groupby(["timestamp", "yAxis"]).size().reset_index(name="amount")
    )
    for ts, y, _ in df_scatter_count[df_scatter_count.amount > 1].itertuples(
        index=False
    ):
        _compute_nonoverlapping_coordinates_per_box(df_scatter, ts, y)
    return df_scatter


def preprocess_data(df):
    _compute_timestamp_fields(df)
    week_band_dates = _compute_week_bands(df)

    min_radius, max_radius = _compute_piechart_radii(week_band_dates)
    df_scatter = _collect_scatterplot_data(df, min_radius, max_radius)
    # In case multiple circles have to plotted on the same x-/y-coordinates, they should be plotted in box and non-
    # overlapping. For example, the following two files were edited on the same date (x-axis, May 15th) and each have
    # one commit, the metric that is put on the y-axis.
    #           timestamp           pieGroupId  yAxis  nodeSize                nodeRadius
    # 2025-05-15 12:00:00   repoFilter/main.go      1         2 1 days 12:04:28.879668049
    # 2025-05-15 12:00:00   repoGitLog/main.go      1         2 1 days 12:04:28.879668049
    # To plot these in a non-overlapping way, one has to compute center points for the scatter plot circles that are
    # both floating point numbers in the range of the bounding box
    df_scatter = _compute_nonoverlapping_coordinates(df_scatter)

    df_pie_charts = _collect_piechart_data(df, df_scatter)
    df_boxes = _compute_group_bounding_box(_collect_group_box_data(df_scatter))

    return week_band_dates, df_scatter, df_pie_charts, df_boxes


def create_plot(
    week_band_dates,
    df_scatter,
    df_pie_charts,
    df_boxes,
    title="Default",
    nodeLabel="Node",
    yAxisLabel="Y",
    rSizeLabel="Size",
):

    color_map = factor_cmap(
        "pieGroupId",
        palette="Category20_20",  # "Colorblind8"
        factors=df_scatter.pieGroupId.unique(),
    )
    hatch_pattern_map = factor_hatch(
        "sliceGroupId",
        patterns=[
            "dot",
            "ring",
            "vertical_line",
            "cross",
            "horizontal_dash",
            "vertical_dash",
            "spiral",
            "right_diagonal_line",
            "left_diagonal_line",
            "diagonal_cross",
            "right_diagonal_dash",
            "left_diagonal_dash",
            "horizontal_wave",
            "vertical_wave",
            "criss_cross",
        ],
        factors=df_pie_charts.sliceGroupId.unique(),
    )

    p = figure(
        sizing_mode="stretch_width",  # alternatively: "stretch_both",
        height=800,
        title=title,
        toolbar_location=None,
        # y_axis_type="log",
        x_axis_type="datetime",
        y_range=(0.0, df_pie_charts.yAxis.max() + 2.0),
    )

    # Create gray background bands
    boxes = [
        BoxAnnotation(
            fill_color="#bbbbbb",
            fill_alpha=0.1,
            left=week_start,
            right=week_end + pd.to_timedelta(1, unit="d"),
            # https://github.com/bokeh/bokeh/issues/13980#issuecomment-2226960920
            propagate_hover=True,
        )
        for week_start, week_end in week_band_dates
    ]
    p.renderers.extend(boxes)

    scatter_data_source = ColumnDataSource(data=df_scatter)
    circles = p.circle(
        x="x",
        y="y",
        radius="nodeRadius",
        fill_color=None,
        line_width=6,
        line_color=color_map,
        legend_group="pieGroupId",
        source=scatter_data_source,
    )

    pie_data_source = ColumnDataSource(data=df_pie_charts)
    p.annular_wedge(
        # x="timestamp",
        # y="yAxis",
        x="x",
        y="y",
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

    box_data_source = ColumnDataSource(data=df_boxes)
    p.block(
        x="timestamp",
        y="yAxis",
        width="width",
        height="height",
        # fill_alpha=1.0,
        fill_color=None,
        line_color="black",
        # line_dash=[],
        # line_dash_offset=0,
        line_join="bevel",
        line_width=1,
        source=box_data_source,
    )

    p.add_tools(
        HoverTool(
            tooltips=[
                # TODO: Set proper name and style it
                (nodeLabel, "@pieGroupId"),
                ("Timestamp", "@timestamp{%F}"),
                (yAxisLabel, "@yAxis"),  # e.g., Commit
                (rSizeLabel, "@nodeSize"),  # e.g., Churn
            ],
            formatters={
                "@timestamp": "datetime",
            },
            # https://discourse.bokeh.org/t/use-hovertool-for-some-glyphs-but-not-others-in-a-plot/10749/2
            renderers=[circles],
        )
    )

    # I would like to have a highlight option, but it does not seem to exist yet
    # https://github.com/bokeh/bokeh/issues/8841
    p.legend.click_policy = "mute"

    # https://stackoverflow.com/a/62159166
    # https://docs.bokeh.org/en/latest/docs/examples/styling/plots/legend_location_outside.html
    p.add_layout(p.legend[0], "right")

    return p


def create_repopie_plot(
    title="Default title", nodeLabel="Node", yAxisLabel="Y", rSizeLabel="Size"
):
    df = read_data()
    week_band_dates, df_scatter, df_pie_charts, df_boxes = preprocess_data(df)
    p = create_plot(
        week_band_dates,
        df_scatter,
        df_pie_charts,
        df_boxes,
        title=title,
        nodeLabel=nodeLabel,
        yAxisLabel=yAxisLabel,
        rSizeLabel=rSizeLabel,
    )
    return p


def main():
    args = docopt(__doc__)
    print(args)
    p = create_repopie_plot(
        title=args["--title"],
        nodeLabel=args["--nodecategory"],
        yAxisLabel=args["--y"],
        rSizeLabel=args["--r"],
    )
    # TODO: Here, I want to save the bokeh plot so that I can embed it in a markdown file and so that its contents are
    #  rendered on GitHub.
    show(p)
