from collections import defaultdict
from datetime import timedelta

from dateutil.parser import parse as date_parse
from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, func, Table
from sqlalchemy.sql import select

from plenario.database import redshift_Base as RBase, redshift_session as r_session
from plenario.database import session, redshift_engine as r_engine
from plenario.sensor_network.sensor_models import NodeMeta


def _apply_aggregates(table, selects, datetimes):
    """Apply the select statements for each datetime and return the results.

    :param table: (SQLAlchemy) reflect feature of interest table
    :param selects: (list) of SQLAlchemy prepared statements
    :param datetimes: (list) of datetime delimiters
    :returns: (list) rowproxy (and rowproxy-like) objects"""

    aggregates = list()

    for i in range(0, len(datetimes) - 1):
        query = select(selects).where(and_(
            table.c.datetime >= datetimes[i],
            table.c.datetime < datetimes[i + 1]
        )).group_by("time_bucket")
        payload = r_session.execute(query).fetchall()

        empty_placeholder = [{
            # Drop the microseconds for display
            "time_bucket": datetimes[i].isoformat().split("+")[0],
            "count": 0
        }]

        aggregates += payload if payload else empty_placeholder

    return aggregates


def _format_aggregates(aggregates, agg_label):
    """Given a list of row proxies, format them into serveable JSON.

    :param aggregates: (SQLAlchemy) row proxy objects (imitateable with dicts)
    :param agg_label: (str) name of the aggregate function used
    :returns: (list) of dictionary objects that can be dumped to JSON"""

    results = list()
    for agg in aggregates:
        aggregate_json = defaultdict(dict)

        for key in agg.keys():
            if key == "time_bucket":
                aggregate_json["time_bucket"] = agg[key]
            elif key == "count":
                aggregate_json["count"] = agg[key]
            elif "count" in key:
                aggregate_json[key.split("_")[0]]["count"] = agg[key]
            else:
                aggregate_json[key][agg_label] = agg[key]

        results.append(aggregate_json)

    return results


def _generate_aggregate_selects(table, target_columns, agg_fn, agg_unit):
    """Return the select statements used to generate a time bucket and apply
    aggregation to each target column.

    :param table: (SQLAlchemy) reflected table object
    :param target_columns: (list) contains strings
    :param agg_fn: (function) compiles to a prepared statement
    :param agg_unit: (str) used by date_trunc to generate time buckets
    :returns: (list) containing SQLAlchemy prepared statements"""

    selects = [func.date_trunc(agg_unit, table.c.datetime).label("time_bucket")]

    meta_columns = ("node_id", "datetime", "meta_id", "sensor")
    for col in table.c:
        if col.name in meta_columns:
            continue
        if col.name not in target_columns:
            continue
        if str(col.type).split("(")[0] != "DOUBLE PRECISION":
            continue
        selects.append(agg_fn(col).label(col.name))
        selects.append(func.count(col).label(col.name + "_count"))

    return selects


def _generate_datetime_range(start_datetime, end_datetime, unit):
    """Helper function for creating datetimes used to construct a series.

    :param start_datetime: (datetime)
    :param end_datetime: (datetime)
    :param unit: (str) unit by which series is broken up (hours, days, ...)
    :returns: (list) of datetimes"""

    start_datetime = start_datetime.replace(tzinfo=None)
    end_datetime = end_datetime.replace(tzinfo=None)

    dt_range = list()
    current_datetime = start_datetime
    while current_datetime <= end_datetime:
        try:
            dt_range.append(current_datetime)
            current_datetime += timedelta(**{unit + "s": 1})
        except TypeError:
            current_datetime += relativedelta(**{unit + "s": 1})
    return dt_range


def _reflect(table_name, metadata, engine):
    """Helper function for an oft repeated block of code.

    :param table_name: (str) table name
    :param metadata: (MetaData) SQLAlchemy object found in a declarative base
    :param engine: (Engine) SQLAlchemy object to send queries to the database
    :returns: (Table) SQLAlchemy object"""

    return Table(
        table_name,
        metadata,
        autoload=True,
        autoload_with=engine
    )


def _valid_columns(node, target_sensors, target_feature_properties):
    """Retrieve the set of valid feature properties to return, given
    feature and sensor filters.

    :param node: (str) node id
    :param target_sensors: (list) containing sensor ids
    :param target_feature_properties: (dict) map of target FOI properties
    :returns: (set) column keys to be used in the aggregate query"""

    select_node_meta = session.query(NodeMeta).filter(NodeMeta.id == node)
    target_node = select_node_meta.first()
    sensors = target_node.sensors

    columns = set()
    for sensor in sensors:
        if target_sensors:
            if sensor.name not in target_sensors:
                continue
        for val in sensor.observed_properties.values():
            current_feature = val.split(".")[0]
            current_property = val.split(".")[1]
            if current_feature not in target_feature_properties:
                continue
            # We will only check against properties if properties were specified
            # ex. magnetic_field.x, magnetic_field.y ...
            if target_feature_properties[current_feature]:
                if current_property not in target_feature_properties[current_feature]:
                    continue
            columns.add(val.split(".")[1].lower())

    return columns


def _zero_out_datetime(dt, unit):
    """To fix a super obnoxious issue where datetrunc (or SQLAlchemy) would
    break up resulting values if provided a datetime with nonzero values more
    granular than datetrunc expects. Ex. calling datetrunc("hour", ...) with
    a datetime such as 2016-09-20 08:12:12.

    Note that if any unit greater than an hour is provided, this method will
    zero hours and below, nothing more.

    :param dt: (datetime) to zero out
    :param unit: (str) from what unit of granularity do we zero
    :returns: (datetime) a well-behaved, non query-breaking datetime"""

    units = ["year", "month", "day", "hour", "minute", "second", "microsecond"]
    i = units.index(unit) + 1
    for zeroing_unit in units[i:]:
        try:
            dt = dt.replace(**{zeroing_unit: 0})
        except ValueError:
            pass
    return dt


def aggregate(args, agg_label, agg_fn):
    """Generate aggregates on node features of interest organized into chunks
    of time.

    :param args: (ValidatorResult) validated user parameters
    :param agg_label: (str) name of the aggregate function being used
    :param agg_fn: (function) aggregate function that is being applied
    :returns: (list) of dictionary objects that can be dumped to JSON"""

    expected = ("node_id", "feature", "start_datetime", "end_datetime", "sensors", "agg_unit")
    node, feature, start_dt, end_dt, sensors, agg_unit = (args.data.get(k) for k in expected)

    # Format the datetime parameters
    start_dt = date_parse(start_dt)
    start_dt = _zero_out_datetime(start_dt, agg_unit)
    end_dt = date_parse(end_dt)

    # Break up comma-delimited query arguments
    target_features = feature.split(",")
    target_sensors = sensors.split(",") if sensors else None

    # Generate a map of the target features and properties
    target_feature_properties = dict()
    for feature in target_features:
        try:
            feature, f_property = feature.split(".")
            target_feature_properties.setdefault(feature, []).append(f_property)
        except ValueError:
            target_feature_properties[feature] = None

    # Determine which columns, if any, can be aggregated from the target node
    valid_columns = _valid_columns(node, target_sensors, target_feature_properties)
    if not valid_columns:
        raise ValueError("Your query returns no results. You have specified "
                         "filters which are likely contradictory (for example "
                         "filtering on a sensor which doesn't have the feature "
                         "you are aggregating for)")

    # Reflect the target feature of interest table
    obs_table = _reflect(feature.split(".")[0], RBase.metadata, r_engine)

    # Generate the necessary select statements and datetime delimiters
    selects = _generate_aggregate_selects(obs_table, valid_columns, agg_fn, agg_unit)
    datetimes = _generate_datetime_range(start_dt, end_dt, agg_unit)

    # Execute the query and return the formatted results
    results = _apply_aggregates(obs_table, selects, datetimes)
    return _format_aggregates(results, agg_label)


aggregate_fn_map = {
    "avg": lambda args: aggregate(args, "avg", func.avg),
    "std": lambda args: aggregate(args, "std", func.stddev),
    "var": lambda args: aggregate(args, "var", func.variance),
}
