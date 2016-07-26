import json

from sqlalchemy.exc import ProgrammingError

from plenario.database import app_engine
from plenario.etl.point import PlenarioETL
from plenario.models import MetaTable
from tests.test_fixtures.base_test import BasePlenarioTest
from tests.test_fixtures.post_data import roadworks_post_data


class TestValidator(BasePlenarioTest):

    def get_json_response_data(self, endpoint):
        """A little util that does work I found myself repeating alot."""

        response = self.app.get('/v1/api/' + endpoint)
        return json.loads(response.data)

    def test_validator_bad_dataset_name(self):
        endpoint = 'detail'
        query = '?dataset_name=crimez&obs_date__ge=2000'

        resp_data = self.get_json_response_data(endpoint + query)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertEquals(resp_data['meta']['message']['dataset_name'], ['Invalid table name: crimez.'])

    def test_validator_bad_dataset_name_and_date(self):
        endpoint = 'detail'
        query = '?dataset_name=crimez&obs_date__ge=20z00'

        resp_data = self.get_json_response_data(endpoint + query)

        self.assertTrue(len(resp_data['meta']['message']) == 2)
        self.assertEquals(resp_data['meta']['message']['dataset_name'], ['Invalid table name: crimez.'])
        self.assertEquals(resp_data['meta']['message']['obs_date__ge'], ['Not a valid date.'])

    def test_validator_bad_column_name(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&obs_date__ge=2000&fake_column=fake'

        resp_data = self.get_json_response_data(endpoint + query)

        self.assertTrue(len(resp_data['meta']['message']) == 2)
        self.assertTrue('Unused param' in resp_data['meta']['message'][0])
        self.assertTrue('not a valid column' in resp_data['meta']['message'][1])

    def test_validator_incorrect_datatype(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&obs_date__ge=2000&data_type=fake'

        resp_data = self.get_json_response_data(endpoint + query)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertEquals(resp_data['meta']['message']['data_type'], ['Not a valid choice.'])

    def test_shape_validator_incorrect_datatype(self):
        endpoint = 'shapes/pedestrian_streets'
        query = '?data_type=csv'

        resp_data = self.get_json_response_data(endpoint + query)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertEquals(resp_data['meta']['message']['data_type'], ['Not a valid choice.'])

    def test_validator_with_good_column_but_bad_value(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&data_type=json&id="break_me"'

        resp_data = self.get_json_response_data(endpoint + query)

        self.assertTrue(len(resp_data['meta']['message']) == 2)
        self.assertTrue('Unused param' in resp_data['meta']['message'][0])
        self.assertTrue('not a valid value' in resp_data['meta']['message'][1])

    def test_catches_bad_filter_dataset_name(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimez__filter='
        qfilter = '{"op": "eq", "col": "iucr", "val": 0110}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertTrue('Table name crimez could not be found' in resp_data['meta']['message']['crimez'])

    def test_rejects_bad_operator_in_tree(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimes__filter='
        qfilter = '{"op": "eqz", "col": "iucr", "val": 0110}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertTrue('causes error' in resp_data['meta']['message']['crimes'])

    def test_rejects_bad_column_in_tree(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimes__filter='
        qfilter = '{"op": "eq", "col": "iucrrr", "val": 0110}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertTrue('causes error' in resp_data['meta']['message']['crimes'])

    def test_rejects_bad_value_in_tree(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimes__filter='
        qfilter = '{"op": "eq", "col": "iucr", "val": -0110}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertTrue('causes error' in resp_data['meta']['message']['crimes'])

    def test_rejects_empty_tree(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimes__filter='
        qfilter = '{}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertTrue('causes error' in resp_data['meta']['message']['crimes'])

    def test_validator_keeps_meta_params_with_a_filter(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&obs_date__ge=2000&agg=year&crimes__filter='
        qfilter = '{"op": "eq", "col": "iucr", "val": 1150}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)
        self.assertEqual(len(resp_data['objects']), 2)

    def test_validator_discards_columns_with_a_filter(self):
        endpoint = 'detail-aggregate'
        query = '?dataset_name=crimes&description=CREDIT CARD FRAUD&crimes__filter='
        qfilter = '{"op": "eq", "col": "iucr", "val": 1150}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertEqual(len(resp_data['meta']['message']), 1)
        self.assertIn('Unused parameter description', resp_data['meta']['message'][0])

    def test_validator_no_table_provided(self):
        endpoint = 'detail-aggregate'
        query = '?description=CREDIT CARD FRAUD'

        resp_data = self.get_json_response_data(endpoint + query)

        self.assertEqual(len(resp_data['meta']['message']), 1)
        self.assertIn('Missing data for required field.', resp_data['meta']['message']['dataset_name'])

    def test_catches_bad_filter_op_keyword(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimes__filter='
        qfilter = '{"opz": "eq"}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertIn('Invalid keyword', resp_data['meta']['message']['crimes'])

    def test_catches_bad_filter_col_keyword(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimes__filter='
        qfilter = '{"op": "eq", "colz": "iucr", "val": 1150}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertIn('invalid keyword', resp_data['meta']['message']['crimes'])

    def test_catches_bad_filter_val_keyword(self):
        endpoint = 'detail'
        query = '?dataset_name=crimes&crimes__filter='
        qfilter = '{"op": "eq", "col": "iucr", "valz": 1150}'

        resp_data = self.get_json_response_data(endpoint + query + qfilter)

        self.assertTrue(len(resp_data['meta']['message']) == 1)
        self.assertIn('invalid keyword', resp_data['meta']['message']['crimes'])

    def test_updates_index_and_validates_correctly(self):

        # Adds a MetaTable record.
        self.app.post('/add?is_shapefile=false', data=roadworks_post_data)
        meta = MetaTable.get_by_dataset_name('roadworks')
        # Creates the table.
        PlenarioETL(meta).add()

        # Perform a query on the newly added dataset (to check if the
        # validator allows the query through).
        query = '/v1/api/detail?dataset_name=roadworks&obs_date__ge=2000'
        response = self.app.get(query)
        data = json.loads(response.data)

        self.assertGreaterEqual(len(data['objects']), 100)

    def tearDown(self):

        try:
            app_engine.execute("drop table roadworks")
            app_engine.execute("delete from meta_master where dataset_name = 'roadworks'")
        except ProgrammingError:
            pass
