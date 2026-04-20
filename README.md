# RepoPie 🥧

RepoPie is a tool to display numerical and categorical data over time.
For example, it might be used to display contributions of authors to files of a
Git repository over time. However, the tool is generic. It can be used to
present any kind of data with two numerical values and two categorical values
per data item.

For given data, RepoPie generates a scatter plot where each node may be a pie
chart. The x-axis is currently fixed to an ISO week number, the y-axis value and
the size of a node in the scatter plot are numerical values in the input data.
Per week, and per two categorical values in the input data, nodes and slices of
pie charts are created.


## Usage

RepoPie is a command-line tool. It can be called as illustrated in the following:

```
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

```

As shown, the input data has to be piped into RepoPie via stdin.


## Input Data

The input data has to be in CSV format. Note, the CSV data is piped in directly
without a header line. Per convention, the order of columns is the following:

* First column: `x-axis` value, which has to be a timestamp
* Second column: `y-axis` value, which is a numerical value
* Third column: `node size` , which is a numerical value
* Fourth column: `node` a categorical value which is used to identify nodes in the scatter plot
* Fifth column: `slize` a categorical value which is used to identify slice in pie chart nodes in the scatter plot


For instance, the example input data in
[`data/example_input/example_data.csv`](./data/example_input/example_data.csv)
It consists of the number of commits (second column) and the sum of added and deleted lines, i.e., churn, of respective commits (third column) that an author (fifth column) performed on a file (fourth column) on the given day (timestamp in the first column).

```csv
2025-07-02,1,126,cmd/repopie/main.go,ropf@itu.dk
2025-05-14,1,96,repoPie/main.go,auso@itu.dk
2025-05-12,1,13,repoPie/main.go,auso@itu.dk
2025-05-12,1,2,repoFilter/main.go,astrid.baggekjaer@gmail.com
2025-05-09,1,41,repoFilter/main.go,jukl@itu.dk
```

This input data has to be provided by you, the user. You can generate it however
you want to. In case of visualizing contributions to a Git repository over time,
you might generate it with `git log` filtered and preprocessed accordingly.

In case the columns of your CSV input data are ordered differently, you have to
reorder them **before** piping it into RepoPie, e.g., via `paste`:

```bash
paste <(cut -d, -f1 data/example_data.csv) <(cut -d, -f4 data/example_data.csv) <(cut -d, -f5 data/example_data.csv) <(cut -d, -f3 data/example_data.csv) <(cut -d, -f2 data/example_data.csv)
```


## Output

When calling RepoPie, e.g., via the following command, it generates an HTML
file containing a [Bokeh](https://bokeh.org/) visualization. The output corresponding to the exemplary input data is
provided in [`data/example_output/example.html`](./data/example_output/example.html)

```bash
cat data/example_data2.csv | \
  repopie --y=y --r=size --title=$(pwd) --nodecategory=thing --slicecategory=subthings
```


## Installation

