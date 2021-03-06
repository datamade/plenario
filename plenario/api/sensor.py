import json

import shapely.geometry
import shapely.wkb
import sqlalchemy as sa
from flask import jsonify, make_response, request
from sqlalchemy import Table, func
from sqlalchemy.exc import SQLAlchemyError

from plenario.api.common import CACHE_TIMEOUT, RESPONSE_LIMIT, cache, crossdomain, date_json_handler, make_cache_key
from plenario.api.response import make_error
from plenario.database import postgres_base, postgres_engine as engine, postgres_session
from plenario.utils.helpers import get_size_in_degrees


@cache.cached(timeout=CACHE_TIMEOUT, key_prefix=make_cache_key)
@crossdomain(origin='*')
def weather_stations():
    raw_query_params = request.args.copy()

    stations_table = Table(
        'weather_stations',
        postgres_base.metadata,
        autoload=True,
        autoload_with=engine,
        extend_existing=True
    )

    valid_query, query_clauses, resp, status_code = make_query(stations_table, raw_query_params)
    if valid_query:

        resp['meta']['status'] = 'ok'
        base_query = postgres_session.query(stations_table)

        for clause in query_clauses:
            print(('weather_stations(): filtering on clause', clause))
            base_query = base_query.filter(clause)

        values = [r for r in base_query.all()]
        fieldnames = [f for f in list(stations_table.columns.keys())]

        for value in values:
            d = {f: getattr(value, f) for f in fieldnames}
            loc = bytes(value.location.data)
            d['location'] = shapely.wkb.loads(loc).__geo_interface__
            resp['objects'].append(d)

    resp['meta']['query'] = raw_query_params
    resp = make_response(
        json.dumps(resp, default=date_json_handler),
        status_code
    )
    resp.headers['Content-Type'] = 'application/json'
    return resp


@cache.cached(timeout=CACHE_TIMEOUT, key_prefix=make_cache_key)
@crossdomain(origin='*')
def weather(table):
    raw_query_params = request.args.copy()

    weather_table = Table(
        'dat_weather_observations_{}'.format(table),
        postgres_base.metadata,
        autoload=True,
        autoload_with=engine,
        extend_existing=True
    )

    stations_table = Table(
        'weather_stations',
        postgres_base.metadata,
        autoload=True,
        autoload_with=engine,
        extend_existing=True
    )

    valid_query, query_clauses, resp, status_code = make_query(weather_table,
                                                               raw_query_params)

    if valid_query:
        resp['meta']['status'] = 'ok'
        base_query = postgres_session.query(weather_table, stations_table)
        base_query = base_query.join(
            stations_table,
            weather_table.c.wban_code == stations_table.c.wban_code
        )

        for clause in query_clauses:
            base_query = base_query.filter(clause)

        try:
            base_query = base_query.order_by(
                getattr(weather_table.c, 'date').desc()
            )
        except AttributeError:
            base_query = base_query.order_by(
                getattr(weather_table.c, 'datetime').desc()
            )
        base_query = base_query.limit(RESPONSE_LIMIT)

        if raw_query_params.get('offset'):
            offset = raw_query_params['offset']
            base_query = base_query.offset(int(offset))

        values = [r for r in base_query.all()]
        weather_fields = list(weather_table.columns.keys())
        station_fields = list(stations_table.columns.keys())
        weather_data = {}
        station_data = {}

        for value in values:
            wd = {f: getattr(value, f) for f in weather_fields}
            sd = {f: getattr(value, f) for f in station_fields}
            if weather_data.get(value.wban_code):
                weather_data[value.wban_code].append(wd)
            else:
                weather_data[value.wban_code] = [wd]
            loc = bytes(value.location.data)
            sd['location'] = shapely.wkb.loads(loc).__geo_interface__
            station_data[value.wban_code] = sd

        for station_id in list(weather_data.keys()):
            d = {
                'station_info': station_data[station_id],
                'observations': weather_data[station_id],
            }
            resp['objects'].append(d)
        resp['meta']['total'] = sum([len(r['observations']) for r in resp['objects']])

    resp['meta']['query'] = raw_query_params
    resp = make_response(
        json.dumps(resp, default=date_json_handler),
        status_code
    )
    resp.headers['Content-Type'] = 'application/json'
    return resp


def year_if_valid(year_str):
    """Returns int from 2000 to 2020 if year_str is valid. Otherwise False
    
    :param year_str:
    :return: False | int
    """
    valid_years = [n + 2000 for n in range(20)]  # 2000 through 2019
    return _string_in_int_range(year_str, valid_years)


def month_if_valid(month_str):
    """Returns int from 1 to 12 if month_str is valid. Otherwise False.
    
    :param month_str: String submitted by user in month field
    :return: False | int
    """
    valid_months = [n + 1 for n in range(12)]  # 1 through 12
    return _string_in_int_range(month_str, valid_months)


def _string_in_int_range(maybe_int, int_range):
    # No nulls, empties
    if not maybe_int:
        return False
    # Can we cast it?
    try:
        as_int = int(maybe_int)
    except ValueError:
        return False
    # Is it in the range?
    return as_int if as_int in int_range else False


def wban_is_valid(wban):
    """
    :param wban: User-submitted WBAN code
    :return: wban code as provided if valid, otherwise False
    """

    if not wban:
        return False

    try:
        stations_table = Table('weather_stations', postgres_base.metadata,
                               autoload=True, autoload_with=engine, extend_existing=True)
        q = sa.select([stations_table.c['wban_code']]).where(stations_table.c['wban_code'] == wban)
        result = postgres_session.execute(q)
    except SQLAlchemyError:
        postgres_session.rollback()
        return False

    matched_wban = result.first()
    if not bool(matched_wban):
        return False

    return True


def wban_list_if_valid(wban_list_str):
    if not wban_list_str:
        return False
    wban_candidate_list = wban_list_str.split(',')

    # If user submits a _lot_ of WBANs, the inefficiency of
    # making one DB call per WBAN will be noticeable.
    # But assuming a handful (< 10) at a time, this is fine for a feature
    # that is designed as a kludge that we do not officially support.
    return [w for w in wban_candidate_list if wban_is_valid(w)]


@crossdomain(origin='*')
def weather_fill():
    from plenario.tasks import update_weather

    args = request.args.copy()
    year = year_if_valid(args.get('year'))
    if not year:
        return make_error('Must supply a year between 2000 and 2019', 400)

    month = month_if_valid(args.get('month'))
    if not month:
        return make_error('Must supply month as number between 1 and 12', 400)

    wbans = wban_list_if_valid(args.get('wbans'))
    if not wbans:
        return make_error('WBAN list misformatted or no WBANS provided are '
                          'available. Check /weather-stations', 400)

    task_id = update_weather.delay(month=month, year=year, wbans=wbans).id
    return jsonify({
        'message': 'Successfully queued weather update.',
        'task_id': task_id
    })


# make_query is a holdover from the old API implementation that used Master Table
def make_query(table, raw_query_params):
    table_keys = list(table.columns.keys())
    args_keys = list(raw_query_params.keys())
    resp = {
        'meta': {
            'status': 'error',
            'message': '',
        },
        'objects': [],
    }
    status_code = 200
    query_clauses = []
    valid_query = True

    if 'offset' in args_keys:
        args_keys.remove('offset')
    if 'limit' in args_keys:
        args_keys.remove('limit')
    if 'order_by' in args_keys:
        args_keys.remove('order_by')
    if 'weather' in args_keys:
        args_keys.remove('weather')

    for query_param in args_keys:

        try:
            field, operator = query_param.split('__')
        except ValueError:
            field = query_param
            operator = 'eq'

        query = None
        query_value = raw_query_params.get(query_param)
        column = table.columns.get(field)

        if field not in table_keys:
            resp['meta']['message'] = '{!r} is not a valid field name'.format(field)
            status_code = 400
            valid_query = False
        elif operator == 'in':
            query = column.in_(query_value.split(','))
            query_clauses.append(query)
        elif operator == 'within':
            geo = json.loads(query_value)

            if 'features' in list(geo.keys()):
                val = geo['features'][0]['geometry']
            elif 'geometry' in list(geo.keys()):
                val = geo['geometry']
            else:
                val = geo

            if val['type'] == 'LineString':
                shape = shapely.geometry.asShape(val)
                lat = shape.centroid.y
                # 100 meters by default
                x, y = get_size_in_degrees(100, lat)
                val = shape.buffer(y).__geo_interface__

            val['crs'] = {'type': 'name', 'properties': {'name': 'EPSG:4326'}}
            query = column.ST_Within(func.ST_GeomFromGeoJSON(json.dumps(val)))
            query_clauses.append(query)
        elif operator.startswith('time_of_day'):
            if operator.endswith('ge'):
                query = func.date_part('hour', column).__ge__(query_value)
            elif operator.endswith('le'):
                query = func.date_part('hour', column).__le__(query_value)
            query_clauses.append(query)
        else:

            try:
                attr = list([e for e in ['%s', '%s_', '__%s__'] if hasattr(column, e % operator)])[0] % operator
            except IndexError:
                msg = '{!r} is not a valid query operator'
                resp['meta']['message'] = msg.format(operator)
                status_code = 400
                valid_query = False
                break

            if query_value == 'null':  # pragma: no cover
                query_value = None

            query = getattr(column, attr)(query_value)
            query_clauses.append(query)

    return valid_query, query_clauses, resp, status_code
